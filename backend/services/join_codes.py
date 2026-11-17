"""分享码：8 位大写字母+数字，朋友输入它加入同一行程的实时协作。

字符集去掉 I/O/0/1，口头转述或截图辨认时不容易看错。不重复的保证是
数据库唯一索引 + 生成冲突重试，而不是「先查后插」——后者在并发下仍可能撞码。
"""
import secrets

from sqlalchemy.exc import IntegrityError

# 32 个字符，8 位约 1.1e12 种组合；去掉了 I/O/0/1 四个易混字符。
ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
CODE_LENGTH = 8
# 撞码重试上限：32^8 空间下连续撞 5 次的概率可以忽略，超出说明索引/数据异常。
MAX_ATTEMPTS = 5
# 加入失败统一口径：不区分「码不存在 / 已停用 / 行程已删」，避免泄露行程是否存在。
INVALID_MESSAGE = '分享码无效或已停用，请向朋友确认。'

def generate() -> str:
    """随机生成分享码：用 secrets 而非 random，避免序列被预测后枚举他人行程。"""
    return ''.join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))

def normalize(code: str | None) -> str:
    """用户输入统一去空白转大写：小写、前后空格都不影响加入。"""
    return (code or '').strip().upper()

def is_well_formed(code: str) -> bool:
    """格式快速校验：长度与字符集都不对就不必查库。"""
    return len(code) == CODE_LENGTH and all(char in ALPHABET for char in code)

def assign(db, trip) -> str | None:
    """给行程写入新分享码并提交，返回码；连续撞码返回 None 由调用方报错。

    唯一性只靠 ix_trips_join_code：两个行程并发拿到同一个码时，后提交的一次
    触发 IntegrityError，回滚后换一个码重试，绝不会出现两行同码。
    """
    for _ in range(MAX_ATTEMPTS):
        trip.join_code = generate()
        try:
            db.commit()
            return trip.join_code
        except IntegrityError:
            # 撞码（或极端并发下同一行程被同时改码）：回滚后换码重试。
            db.rollback()
    return None

def clear(db, trip) -> None:
    """停用分享码：置空即失效（唯一索引允许多个 NULL），没生成过则什么都不做。"""
    if not trip.join_code:
        return
    trip.join_code = None
    db.commit()
