from pydantic import BaseModel


# ========== 认证相关 ==========

class LoginRequest(BaseModel):
    student_id: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str


class UserInfo(BaseModel):
    id: int
    student_id: str
    name: str
    role: str
    created_at: str


class PasswordUpdate(BaseModel):
    """PUT /api/me/password 请求"""
    old_password: str
    new_password: str


# ========== 对话相关 ==========

class ConversationCreate(BaseModel):
    title: str = "新对话"


class ConversationOut(BaseModel):
    id: int
    title: str
    created_at: str
    subject: str | None = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: str


class ChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str
    subject: str | None = None


# ========== 反馈相关（v4.0 M1） ==========

class FeedbackCreate(BaseModel):
    """POST /api/feedback 请求"""
    message_id: int
    rating: str  # up=点赞 / down=点踩
    reason: str | None = None  # rating=down 时必填（后端校验）


class FeedbackItem(BaseModel):
    """GET /api/admin/feedbacks 列表项"""
    id: int
    rating: str
    reason: str | None = None
    student_id: str
    student_name: str
    question: str | None = None  # 上一条学生提问（应用层关联）
    answer: str
    knowledge_point_ids: list[str] = []
    created_at: str


class FeedbackListOut(BaseModel):
    total: int
    items: list[FeedbackItem]


# ========== 检索可观测相关（v4.0 M1） ==========

class KbStatsByDay(BaseModel):
    date: str
    total: int
    empty: int
    degraded: int


class KbStatsOut(BaseModel):
    """GET /api/admin/kb/stats 响应"""
    total: int
    empty_count: int
    empty_rate: float
    degraded_count: int
    avg_elapsed_ms: int
    by_day: list[KbStatsByDay]
    by_status: dict[str, int]


class HotKpItem(BaseModel):
    """GET /api/admin/kb/hot-kps 列表项"""
    kp_id: str
    count: int


# ========== 全局设置与权益（v4.0 M1） ==========

class AppSettingsOut(BaseModel):
    """GET /api/admin/settings 响应（值已按键转型）"""
    daily_question_limit_default: int
    memory_enabled_default: bool
    chat_concurrency: int
    chat_queue_size: int
    profile_update_interval: int


class AppSettingsUpdate(BaseModel):
    """PUT /api/admin/settings 请求（部分更新，只传要改的键）"""
    daily_question_limit_default: int | None = None
    memory_enabled_default: bool | None = None
    chat_concurrency: int | None = None
    chat_queue_size: int | None = None
    profile_update_interval: int | None = None


class EntitlementsUpdate(BaseModel):
    """PUT /api/admin/students/{id}/entitlements 请求（null=恢复跟随全局）"""
    daily_question_limit: int | None = None
    memory_enabled: bool | None = None


# ========== 科目相关（枚举由知识库侧维护，见 doc/知识库科目枚举约定.md） ==========

class SubjectItem(BaseModel):
    subject: str
    name: str
    status: str


# ========== 大模型管理相关 ==========

class ModelConfigOut(BaseModel):
    id: int
    provider: str
    model_name: str
    display_name: str
    price_in: float
    price_out: float
    enabled: bool
    is_active: bool
    created_at: str


class ModelConfigCreate(BaseModel):
    provider: str = "ali"
    model_name: str
    display_name: str
    price_in: float = 0
    price_out: float = 0
    enabled: bool = True


class ModelConfigUpdate(BaseModel):
    provider: str | None = None
    model_name: str | None = None
    display_name: str | None = None
    price_in: float | None = None
    price_out: float | None = None
    enabled: bool | None = None


class UsageByModel(BaseModel):
    model_name: str
    tokens: int
    cost: float


class UsageDaily(BaseModel):
    date: str
    tokens: int
    cost: float


class UsageStatsOut(BaseModel):
    total_tokens: int
    total_cost: float
    today_tokens: int
    today_cost: float
    by_model: list[UsageByModel]
    daily: list[UsageDaily]


# ========== 管理员相关 ==========

class StudentCreate(BaseModel):
    student_id: str
    name: str
    password: str


class StudentUpdate(BaseModel):
    name: str | None = None
    password: str | None = None


class StatsResponse(BaseModel):
    total_students: int
    total_conversations: int
    today_active_users: int
