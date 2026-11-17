"""重置数据库（仅开发/测试用）：空库重建，不做数据迁移。

用法：
    python scripts/db_reset.py                     # 预览：只列出将被删除的对象
    python scripts/db_reset.py --yes               # 真正执行
    python scripts/db_reset.py --url postgresql+psycopg://... --yes

- SQLite：删除库文件（含 -wal/-shm）后 create_all + ensure_schema 重建。
- PostgreSQL：删除 public schema 下所有表（含 alembic_version）后执行 alembic upgrade head。
- 目标库从 --url 或 DATABASE_URL 解析；未设置时用本地默认 sqlite 库。
- APP_ENV=production 默认拒绝执行，确需重置必须再加 --force。
- 输出永不打印连接串密码。

退出码：0 成功/预览，1 执行失败，2 因生产环境保护被拒绝。
"""
import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend import db as app_db  # noqa: E402


def masked(url: str) -> str:
    """脱敏后的连接串：日志/终端可能被人看到，密码一律替换成 ***。"""
    try:
        return make_url(url).render_as_string(hide_password=True)
    except Exception:
        return '<无法解析的连接串>'


def resolve_url(cli_url: str | None = None) -> str:
    """--url 优先，其次 DATABASE_URL，最后本地默认 sqlite 库。"""
    return (cli_url or os.getenv('DATABASE_URL') or app_db.DEFAULT_DATABASE_URL).strip()


def sqlite_file(url: str) -> Path | None:
    """取 sqlite 文件路径；内存库或非 sqlite URL 返回 None。"""
    if not app_db.is_sqlite(url):
        return None
    database = (make_url(url).database or '').strip()
    if not database or database == ':memory:':
        return None
    path = Path(database)
    return path if path.is_absolute() else (Path.cwd() / path)


def _public_tables(url: str) -> list[str]:
    """连库读一次表清单；连不上就让异常冒到 main 统一转成失败退出码。"""
    engine = create_engine(url)
    try:
        return sorted(inspect(engine).get_table_names(schema='public'))
    finally:
        engine.dispose()


def _reset_sqlite(url: str, path: Path) -> None:
    """删库文件后重建：SQLite 没有 schema 概念，重建等价于 create_all + ensure_schema。"""
    for suffix in ('', '-wal', '-shm'):
        Path(str(path) + suffix).unlink(missing_ok=True)
    engine = create_engine(url)
    try:
        app_db.configure_engine(engine)
        # 重置脚本有自己的生产保护（--force）：这里直接建表，不再经过启动守卫。
        app_db.Base.metadata.create_all(engine)
        app_db.ensure_schema(engine)
    finally:
        engine.dispose()


def _reset_postgres(url: str) -> None:
    """drop 掉 public 下所有表后用 Alembic 重建：schema 的唯一来源始终是迁移脚本。"""
    engine = create_engine(url)
    try:
        tables = inspect(engine).get_table_names(schema='public')
        with engine.begin() as conn:
            for name in tables:
                quoted = name.replace('"', '""')
                conn.execute(text(f'DROP TABLE IF EXISTS public."{quoted}" CASCADE'))
    finally:
        engine.dispose()
    _alembic_upgrade(url)


def _alembic_upgrade(url: str) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(PROJECT_ROOT / 'alembic.ini'))
    # 显式注入连接串：env.py 优先用它，避免被同名环境变量覆盖。
    config.set_main_option('sqlalchemy.url', url.replace('%', '%%'))
    config.attributes['configure_logger'] = False
    command.upgrade(config, 'head')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='重置数据库（空库重建，仅开发/测试）')
    parser.add_argument('--url', help='目标连接串；默认取 DATABASE_URL')
    parser.add_argument('--yes', action='store_true', help='确认执行（不加只做预览）')
    parser.add_argument('--force', action='store_true', help='APP_ENV=production 时仍然执行（危险）')
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    url = resolve_url(args.url)
    app_env = (os.getenv('APP_ENV') or 'development').strip().lower()
    path = sqlite_file(url)
    if app_db.is_sqlite(url):
        backend = 'sqlite'
    elif app_db.is_postgres(url):
        backend = 'postgresql'
    else:
        backend = '其它'

    print(f'目标数据库：{masked(url)}')
    print(f'类型：{backend}    APP_ENV：{app_env}')

    if backend == '其它':
        print(f'不支持的重置目标（仅支持 sqlite / postgresql）：{masked(url)}', file=sys.stderr)
        return 1
    if backend == 'sqlite' and path is None:
        print('不支持重置内存 SQLite（sqlite:///:memory:）：请指定文件库连接串。', file=sys.stderr)
        return 1

    if backend == 'sqlite':
        files = [Path(str(path) + suffix) for suffix in ('', '-wal', '-shm')]
        existing = [item for item in files if item.exists()]
        if existing:
            print(f'将删除的 SQLite 文件（{len(existing)}）：')
            for item in existing:
                print(f'  - {item}')
        else:
            print('SQLite 库文件尚不存在：将从零创建。')
    else:
        try:
            tables = _public_tables(url)
        except Exception as exc:
            print(f'读取表清单失败：{type(exc).__name__}: {exc}', file=sys.stderr)
            return 1
        print(f'将删除 public schema 下的表（{len(tables)}）：')
        for name in tables:
            print(f'  - {name}')

    if not args.yes:
        print('')
        print('预览模式：未做任何修改。确认后加 --yes 执行。')
        if app_env == 'production':
            print('注意：当前 APP_ENV=production，真正执行还需要 --force。')
        return 0

    if app_env == 'production' and not args.force:
        print('拒绝执行：APP_ENV=production 时默认禁止重置数据库；确需重置请加 --force。', file=sys.stderr)
        return 2

    try:
        if backend == 'sqlite':
            _reset_sqlite(url, path)
        else:
            _reset_postgres(url)
    except Exception as exc:
        print(f'重置失败：{type(exc).__name__}: {exc}', file=sys.stderr)
        return 1

    print('重置完成：库已是空库重建后的最新 schema。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
