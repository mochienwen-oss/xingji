"""PostgreSQL 在线备份：pg_dump custom 格式 + pg_restore 校验 + 滚动保留。

用法：
    python scripts/backup_pg.py --database-url "$DATABASE_URL" --dest-dir backups --keep 7

默认从 DATABASE_URL 读取连接串；只支持 PostgreSQL，SQLite 仍用 scripts/backup_db.py。
密码不会出现在命令行参数里，而是通过 PGPASSWORD 传给子进程。
失败时清理半成品、写 stderr 并以非零码退出，方便 cron/监控直接判断。
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

DEFAULT_DEST_DIR = 'backups'
DEFAULT_KEEP = 7
DEFAULT_TIMEOUT = 300
NAME_PREFIX = 'trip-'
NAME_SUFFIX = '.dump'
_PG_PREFIXES = ('postgresql+psycopg://', 'postgresql+psycopg2://', 'postgres+psycopg://')
_POSTGRES_SCHEMES = ('postgresql://', 'postgres://')
_SSL_MODES = {'disable', 'allow', 'prefer', 'require', 'verify-ca', 'verify-full'}


class BackupError(RuntimeError):
    """备份失败；main() 会把它转成 stderr + 退出码 1。"""


def _normalize_url(raw: str) -> str:
    text = (raw or '').strip()
    for prefix in _PG_PREFIXES:
        if text.startswith(prefix):
            return 'postgresql://' + text[len(prefix):]
    if text.startswith(_POSTGRES_SCHEMES):
        return text
    raise BackupError('只支持 PostgreSQL 连接串（postgresql:// 或 postgresql+psycopg://）')


def parse_database_url(raw: str) -> dict:
    """把 SQLAlchemy/psycopg 连接串拆成 pg_dump 参数；不返回密码明文。"""
    parts = urlsplit(_normalize_url(raw))
    database = unquote(parts.path.lstrip('/')).split('?', 1)[0]
    if not database:
        raise BackupError('连接串缺少数据库名')
    query = parse_qs(parts.query)
    sslmode = (query.get('sslmode') or [''])[0].strip().lower()
    if sslmode and sslmode not in _SSL_MODES:
        raise BackupError(f'不支持的 sslmode：{sslmode}')
    return {
        'host': parts.hostname or '',
        'port': str(parts.port or ''),
        'user': unquote(parts.username or ''),
        'password': unquote(parts.password or ''),
        'database': database,
        'sslmode': sslmode,
    }


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')


def _command(settings: dict, pg_dump: str, target: Path) -> list[str]:
    command = [pg_dump, '--format=custom', '--no-owner', '--no-privileges', '--file', str(target)]
    if settings['host']:
        command += ['--host', settings['host']]
    if settings['port']:
        command += ['--port', settings['port']]
    if settings['user']:
        command += ['--username', settings['user']]
    command += ['--dbname', settings['database']]
    return command


def _run(command: list[str], env: dict, timeout: int, what: str) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command, env=env, capture_output=True, text=True, encoding='utf-8',
            errors='replace', timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise BackupError(f'找不到 {command[0]}：{exc}') from exc
    except subprocess.TimeoutExpired as exc:
        raise BackupError(f'{what}超时（{timeout}s）') from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or '').strip().splitlines()
        reason = detail[-1] if detail else f'退出码 {result.returncode}'
        raise BackupError(f'{what}失败：{reason}')
    return result


def _verify(path: Path, pg_restore: str, env: dict, timeout: int) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise BackupError('pg_dump 没有生成有效文件')
    _run([pg_restore, '--list', str(path)], env, timeout, 'pg_restore 校验')


def _prune(dest_dir: Path, keep: int) -> None:
    backups = [
        (item.stat().st_mtime, item.name, item)
        for item in dest_dir.glob(f'{NAME_PREFIX}*{NAME_SUFFIX}')
        if item.is_file()
    ]
    backups.sort(key=lambda row: (row[0], row[1]), reverse=True)
    for _, _, path in backups[keep:]:
        path.unlink(missing_ok=True)


def backup(
    database_url: str,
    dest_dir: Path,
    keep: int = DEFAULT_KEEP,
    *,
    pg_dump: str = 'pg_dump',
    pg_restore: str = 'pg_restore',
    timeout: int = DEFAULT_TIMEOUT,
) -> Path:
    """生成并校验一份备份；失败不留半成品。"""
    settings = parse_database_url(database_url)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / f'{NAME_PREFIX}{_timestamp()}{NAME_SUFFIX}'
    temp = dest_dir / f'.{target.name}.tmp'
    env = os.environ.copy()
    if settings['password']:
        env['PGPASSWORD'] = settings['password']
    if settings['sslmode']:
        env['PGSSLMODE'] = settings['sslmode']
    try:
        _run(_command(settings, pg_dump, temp), env, timeout, 'pg_dump')
        _verify(temp, pg_restore, env, timeout)
        os.replace(temp, target)
    finally:
        temp.unlink(missing_ok=True)
    _prune(dest_dir, keep)
    try:
        dest_dir.chmod(0o700)
        target.chmod(0o600)
    except OSError:
        # Windows 不支持 POSIX 权限；文件仍能正常备份与恢复。
        pass
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
    parser = argparse.ArgumentParser(description='PostgreSQL 在线备份（pg_dump custom 格式）')
    parser.add_argument('--database-url', default=os.getenv('DATABASE_URL', ''),
                        help='PostgreSQL 连接串；默认读 DATABASE_URL')
    parser.add_argument('--dest-dir', default=DEFAULT_DEST_DIR, help=f'备份目录（默认 {DEFAULT_DEST_DIR}）')
    parser.add_argument('--keep', type=_positive_int, default=DEFAULT_KEEP, help=f'保留最近几份（默认 {DEFAULT_KEEP}）')
    parser.add_argument('--pg-dump', default='pg_dump', help='pg_dump 可执行文件路径')
    parser.add_argument('--pg-restore', default='pg_restore', help='pg_restore 可执行文件路径')
    parser.add_argument('--timeout', type=_positive_int, default=DEFAULT_TIMEOUT, help=f'单步超时秒数（默认 {DEFAULT_TIMEOUT}）')
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if not args.database_url.strip():
        print('备份失败：未提供 PostgreSQL 连接串（--database-url 或 DATABASE_URL）', file=sys.stderr)
        return 1
    try:
        target = backup(
            args.database_url, Path(args.dest_dir).expanduser(), args.keep,
            pg_dump=args.pg_dump, pg_restore=args.pg_restore, timeout=args.timeout,
        )
    except Exception as exc:
        print(f'备份失败：{exc}', file=sys.stderr)
        return 1
    print(f'备份完成：{target.resolve()}（{target.stat().st_size} bytes）')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
