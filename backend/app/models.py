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
