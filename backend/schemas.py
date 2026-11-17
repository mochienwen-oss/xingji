from datetime import date
from typing import Literal
from pydantic import BaseModel, Field, model_validator

class Login(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)

class Register(BaseModel):
    username: str = Field(min_length=2, max_length=80)
    password: str = Field(min_length=8, max_length=200)
    # 邮箱选填：形状在端点层用 accounts.normalize_email 校验，避免引入 email-validator 依赖
    email: str = Field(default='', max_length=254)
    accept_terms: bool = False

class VerifyEmail(BaseModel):
    # token 由邮件链接带出；形状/长度合法但不存在的情形由端点统一 400
    token: str = Field(min_length=1, max_length=200)

class ChangeEmail(BaseModel):
    # email 形状在端点层用 accounts.normalize_email 校验；password 是当前密码，沿用登录的 1..200
    email: str = Field(min_length=1, max_length=254)
    password: str = Field(min_length=1, max_length=200)

class ForgotPassword(BaseModel):
    # identifier 是用户名或邮箱，是否存在交给端点判断（端点始终返回 200，避免账号枚举）
    identifier: str = Field(min_length=1, max_length=254)

class ResetPassword(BaseModel):
    # 长度规则与注册一致；全空白由端点补 422，避免把空格存成密码
    token: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)

class ChangePassword(BaseModel):
    # 当前密码沿用登录的 1..200；新密码长度与注册一致，全空白由端点补 422
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)

class DeleteAccount(BaseModel):
    # 密码是唯一凭证；confirm 必须精确等于“注销”，多一个空格也按端点 422 处理
    password: str = Field(min_length=1, max_length=200)
    confirm: str = Field(min_length=1, max_length=20)

class UpdateTrip(BaseModel):
    title: str = Field(min_length=1, max_length=120)

class RequestPlan(BaseModel):
    city: str = Field(min_length=1, max_length=40)
    days: int = Field(ge=1, le=5)
    start_date: date | None = None
    travelers: int = Field(default=2, ge=1, le=20)
    interests: str = Field(default='', max_length=200)
    pace: Literal['轻松', '适中', '紧凑'] = '适中'
    budget: str = Field(default='', max_length=100)
    must_visit: str = Field(default='', max_length=200)
    transport: Literal['walking', 'driving', 'transit'] = 'transit'

class Place(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    address: str = ''
    location: str
    city: str = Field(default='', max_length=50)
    opentime: str = ''
    cost: str = ''
    source_time: str = ''
    # 高德 POI 每个地点的 photos 实际只有个位数张，前端也只取第一张可用图作封面；
    # 30 已远超真实量级，仅防列表被灌大，请求体总量的硬上限由 BodyLimitMiddleware 兜底。
    photos: list[dict[str, str]] = Field(default_factory=list, max_length=30)
    unavailable: bool = False
    # 只由地图数据源回填，用于区分“地点存在”和“营业时间已核验”。
    verification: dict | None = None

class BudgetUpdate(BaseModel):
    amount_cents: int | None = Field(default=None, ge=0, le=100000000000)

class ExpenseInput(BaseModel):
    amount_cents: int = Field(gt=0, le=100000000000)
    category: Literal['餐饮', '交通', '住宿', '门票', '其他']
    expense_date: date
    place_id: str | None = Field(default=None, max_length=100)
    note: str = Field(default='', max_length=200)

class Stop(BaseModel):
    place: Place
    duration: int = Field(ge=15, le=480)
    reason: str = Field(default='', max_length=300)
    activity: str = Field(default='', max_length=120)
    fixed_time: str | None = Field(default=None, pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    fixed_next_day: bool = False

class Day(BaseModel):
    stops: list[Stop] = Field(max_length=12)
    start_time: str | None = Field(default=None, pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')
    end_time: str | None = Field(default=None, pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')

    # 结束时间早于或等于开始时间不当作错误：README 第 87 行约定按次日计算，
    # 前端时间轴与 route_opt 都按 +1440 分钟处理，这里不再拦成 422。

class UpdateDays(BaseModel):
    days: list[Day] = Field(min_length=1, max_length=5)
    backlog: list[Stop] | None = Field(default=None, max_length=100)
    version: int | None = Field(default=None, ge=0)

class ChatMessage(BaseModel):
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=2000)

class CreateTrip(RequestPlan):
    conversation: list[ChatMessage] = Field(default_factory=list, max_length=100)
    initial_places: list[Place] = Field(default_factory=list, max_length=60)

class PlanningChat(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=20)
    current: dict | None = None

class PlaceIds(BaseModel):
    ids: list[str] = Field(default_factory=list, max_length=60)

class TripChat(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=10)
    version: int | None = Field(default=None, ge=0)

class PreviewAssistant(BaseModel):
    request: RequestPlan
    days: list[Day] = Field(min_length=1, max_length=5)
    backlog: list[Stop] = Field(default_factory=list, max_length=100)
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=10)
    place_notice: str = ''

class SavePreview(BaseModel):
    request: RequestPlan
    days: list[Day] = Field(min_length=1, max_length=5)
    backlog: list[Stop] = Field(default_factory=list, max_length=100)
    conversation: list[ChatMessage] = Field(default_factory=list, max_length=100)

class GuideText(BaseModel):
    text: str = Field(min_length=1, max_length=12000)

class GuideAssignment(BaseModel):
    day: int = Field(ge=1, le=5)
    place_id: str = Field(min_length=1, max_length=100)
    duration: int | None = Field(default=None, ge=15, le=480)

class GuideAdopt(BaseModel):
    assignments: list[GuideAssignment] = Field(min_length=1, max_length=60)
    version: int | None = Field(default=None, ge=0)

class StartDateUpdate(BaseModel):
    start_date: date | None = None
    version: int | None = Field(default=None, ge=0)

class VisibilityUpdate(BaseModel):
    """兼容旧的 {is_public} 调用；新客户端用 mode 表达三级可见性。"""
    is_public: bool | None = None
    mode: Literal['private', 'link', 'public'] | None = None

    @model_validator(mode='after')
    def _check_one(self):
        if self.mode is None and self.is_public is None:
            raise ValueError('is_public 或 mode 至少提供一个')
        return self

class ShareAccess(BaseModel):
    token: str = Field(min_length=1, max_length=100)

class JoinCodeRequest(BaseModel):
    """rotate=true 表示轮换分享码（旧码立即失效）；默认「没有就生成，已有就返回」。"""
    rotate: bool = False

class JoinTripRequest(BaseModel):
    """用户自行填写的分享码：长度上限放宽，格式校验与错误口径统一在服务层。"""
    code: str = Field(min_length=1, max_length=32)

class InspirationBody(BaseModel):
    city: str = Field(min_length=1, max_length=40)
    theme_id: str = Field(min_length=1, max_length=40)
    theme_label: str = Field(default='', max_length=20)
    theme_desc: str = Field(default='', max_length=80)

class ReportCreate(BaseModel):
    reason: str = Field(min_length=1, max_length=20)
    detail: str = Field(default='', max_length=1000)

class ReportResolve(BaseModel):
    action: Literal['hide', 'dismiss']
    note: str = Field(default='', max_length=200)

class PlanForm(RequestPlan):
    """前端草稿里的规划表单：字段与 RequestPlan 完全一致，只放宽城市（还没选目的地）与天数默认值。"""
    city: str = Field(default='', max_length=40)
    days: int = Field(default=3, ge=1, le=5)

class HarnessTurnRequest(BaseModel):
    """一次规划会话回合：客户端带上当前草稿、最近消息和已压缩摘要，服务端不依赖会话表。"""
    session_id: str = Field(default='', max_length=80)
    mode: Literal['explore', 'preview', 'trip'] = 'explore'
    message: str = Field(min_length=1, max_length=2000)
    messages: list[ChatMessage] = Field(default_factory=list, max_length=40)
    form: PlanForm | None = None
    places: list[Place] = Field(default_factory=list, max_length=60)
    # summary/preview 是客户端草稿的自由 dict，契约保持宽松不锁字段；体积由请求体大小中间件兜底。
    summary: dict | None = None
    turn_count: int = Field(default=0, ge=0, le=10000)
    preview: dict | None = None
    trip_id: int | None = Field(default=None, ge=1)
    version: int | None = Field(default=None, ge=0)

class MemoryPreference(BaseModel):
    enabled: bool
