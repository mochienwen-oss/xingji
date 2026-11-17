"""SQLite 在线备份：WAL 模式下不能直接复制 trip.db，必须走 sqlite3 的 backup API。

用法：
    python scripts/backup_db.py [--source trip.db] [--dest-dir backups] [--keep 7]

默认 source 从 DATABASE_URL 解析 sqlite 文件，否则 trip.db；dest-dir 默认 backups。
成功打印备份路径与字节数；任何失败写 stderr 并以非零退出码结束。
"""
import argparse
import contextlib
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_SOURCE = 'trip.db'
DEFAULT_DEST_DIR = 'backups'
DEFAULT_KEEP = 7
NAME_PREFIX = 'trip-'
NAME_SUFFIX = '.db'
_SQLITE_PREFIXES = ('sqlite+pysqlite:///', 'sqlite:///')


def _sqlite_path(url: str) -> str | None:
    """从 SQLAlchemy 的 sqlite URL 取出文件路径；内存库/其它方言返回 None。"""
    raw = (url or '').strip()
    for prefix in _SQLITE_PREFIXES:
        if raw.startswith(prefix):
            path = raw[len(prefix):].split('?', 1)[0].split('#', 1)[0].strip()
            # sqlite:////abs/path 剩下 /abs/path；sqlite:///./trip.db 剩下 ./trip.db。
            if not path or path == ':memory:':
                return None
            return path
    return None


def resolve_source(value: str | None = None) -> Path:
    """--source 优先；其次 DATABASE_URL 的 sqlite 路径；最后默认 ./trip.db。"""
    if value:
        return Path(value).expanduser()
    from_url = _sqlite_path(os.getenv('DATABASE_URL', ''))
    return Path(from_url or DEFAULT_SOURCE).expanduser()


def _timestamp() -> str:
    """UTC 秒级时间戳；同一秒重复执行会覆盖同名备份，测试用 monkeypatch 控制。"""
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _prune(dest_dir: Path, keep: int) -> None:
    """按 mtime 从新到旧保留最近 keep 份；mtime 相同用文件名兜底，保证结果稳定。"""
    backups = [
        (item.stat().st_mtime, item.name, item)
        for item in dest_dir.glob(f'{NAME_PREFIX}*{NAME_SUFFIX}')
        if item.is_file()
    ]
    backups.sort(key=lambda row: (row[0], row[1]), reverse=True)
    for _, _, path in backups[keep:]:
        path.unlink(missing_ok=True)


def backup(source: Path, dest_dir: Path, keep: int) -> Path:
    """在线备份 source 到 dest_dir，返回最终备份文件；失败抛异常且不留半成品。"""
    if not source.is_file():
        raise FileNotFoundError(f'源数据库不存在：{source}')
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f'{NAME_PREFIX}{_timestamp()}{NAME_SUFFIX}'
    temp = dest_dir / f'.{target.name}.tmp'
    try:
        # 先写隐藏临时文件再 os.replace：目标文件只会以完整备份出现。
        with contextlib.closing(sqlite3.connect(source, timeout=10)) as source_conn, \
                contextlib.closing(sqlite3.connect(temp)) as dest_conn:
            source_conn.backup(dest_conn)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    _prune(dest_dir, keep)
    return target


def _positive_int(value: str) -> int:
    try:
        number = int(value)
    except ValueError:
        number = 0
    if number < 1:
        raise argparse.ArgumentTypeError(f'需要正整数：{value}')
    return number


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='SQLite 在线备份（WAL 安全）')
    parser.add_argument('--source', help='源数据库路径；默认从 DATABASE_URL 解析，否则 trip.db')
    parser.add_argument('--dest-dir', default=DEFAULT_DEST_DIR, help=f'备份目录（默认 {DEFAULT_DEST_DIR}）')
    parser.add_argument('--keep', type=_positive_int, default=DEFAULT_KEEP, help=f'保留最近几份（默认 {DEFAULT_KEEP}）')
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    source = resolve_source(args.source)
    dest_dir = Path(args.dest_dir).expanduser()
    try:
        target = backup(source, dest_dir, args.keep)
    except Exception as exc:  # 备份脚本把所有失败都转成 stderr + 非零退出码
        print(f'备份失败：{exc}', file=sys.stderr)
        return 1
    size = target.stat().st_size
    print(f'备份完成：{target.resolve()}（{size} bytes）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
