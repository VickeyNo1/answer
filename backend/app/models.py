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
    subject_id: int | None = None


class MessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: str


class ChatRequest(BaseModel):
    conversation_id: int | None = None
    message: str
    subject_id: int | None = None


# ========== 知识库相关 ==========

class DocumentInfo(BaseModel):
    name: str
    chunk_count: int
    created_at: str
    subject_id: int | None = None


# ========== 科目相关 ==========

class SubjectOut(BaseModel):
    id: int
    name: str
    category: str
    description: str = ""
    sort_order: int = 0
    created_at: str


class SubjectCreate(BaseModel):
    name: str
    category: str = "general"
    description: str = ""
    sort_order: int = 0


class SubjectUpdate(BaseModel):
    name: str | None = None
    category: str | None = None
    description: str | None = None
    sort_order: int | None = None


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
