import getpass
import secrets
from dotenv import load_dotenv
load_dotenv()
from sqlalchemy import inspect, select
from .auth import hash_password
from .db import Base, Session, User, engine

def main():
    username = input('用户名: ').strip()
    password = getpass.getpass('密码（至少 8 位）: ')
    if not username or len(username) > 80 or len(password) < 8 or len(password) > 200:
        raise SystemExit('用户名不能为空，密码长度须为 8–200 位。')
    if password != getpass.getpass('再次输入密码: '):
        raise SystemExit('两次密码不一致。')
    # SQLite 本地库允许随手建表；PostgreSQL 的表结构只由 Alembic 管理，
    # 这里若 create_all 会绕过 alembic_version，导致后续 upgrade 冲突。
    if engine.dialect.name == 'sqlite':
        Base.metadata.create_all(engine)
    elif not inspect(engine).has_table('users'):
        raise SystemExit('数据库尚未迁移，请先运行 python -m alembic upgrade head。')
    with Session() as db:
        if db.scalar(select(User).where(User.username == username)):
            raise SystemExit('用户名已存在。')
        db.add(User(username=username, password_hash=hash_password(password), session_nonce=secrets.token_hex(16)))
        db.commit()
    print('用户已创建。')

if __name__ == '__main__':
    main()
