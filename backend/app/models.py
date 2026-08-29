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
    # 图片题目（纯 base64，不含 data: 前缀）；非空时先 OCR 再进入答疑流程（方案 B）
    image_base64: str | None = None


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


# ========== 考试相关（v4.0 M2） ==========

class ExamCreateRequest(BaseModel):
    """POST /api/exams 请求（chapter_ids 为 null/空 = 全科目范围）"""
    subject: str | None = None
    chapter_ids: list[str] | None = None
    counts: dict[str, int]


class ExamQuestionOut(BaseModel):
    """答题用题目（**不含参考答案与解析**，快照仅落库）"""
    seq: int
    question_type: str
    stem: str | None = None
    options: dict | None = None
    materials: str | None = None
    sub_questions: list | None = None
    full_score: float


class ExamCreateResponse(BaseModel):
    id: int
    status: str
    question_count: int
    total_score: float
    questions: list[ExamQuestionOut]


class ExamAnswerSaveItem(BaseModel):
    seq: int
    content: str | None = None


class ExamAnswersSaveRequest(BaseModel):
    """PUT /api/exams/{id}/answers 请求（可多次调用覆盖暂存）"""
    answers: list[ExamAnswerSaveItem]


class ExamSubmitResponse(BaseModel):
    id: int
    status: str  # 有主观题=grading / 纯客观题=graded
    objective_score: float
    pending_subjective: int


class ExamListItem(BaseModel):
    """GET /api/exams 列表项"""
    id: int
    subject: str
    status: str
    question_count: int
    total_score: float
    obtained_score: float | None = None
    created_at: str
    submitted_at: str | None = None


class ExamAnswerDetail(BaseModel):
    """成绩单单题明细（graded 前不含 correct_answer/explanation/score/llm_reason）"""
    seq: int
    question_type: str
    stem: str | None = None
    options: dict | None = None
    materials: str | None = None
    sub_questions: list | None = None
    my_answer: str | None = None
    correct_answer: str | None = None
    explanation: str | None = None
    score: float | None = None
    full_score: float
    llm_reason: str | None = None
    disputed: int = 0
    knowledge_point_ids: list[str] = []


class MasteryKpItem(BaseModel):
    kp_id: str
    rate: float


class MasteryChapterItem(BaseModel):
    chapter_id: str
    rate: float


class MasteryOut(BaseModel):
    """掌握度归因（算式见设计 §4.5），仅 graded 后返回"""
    by_kp: list[MasteryKpItem] = []
    by_chapter: list[MasteryChapterItem] = []
    weak_kps: list[MasteryKpItem] = []


class ExamDetailResponse(BaseModel):
    """GET /api/exams/{id} 成绩单详情"""
    id: int
    subject: str
    status: str
    question_count: int
    total_score: float
    obtained_score: float | None = None
    created_at: str
    submitted_at: str | None = None
    answers: list[ExamAnswerDetail] = []
    mastery: MasteryOut | None = None


# ----- 管理端考试（v4.0 M2 B4） -----

class AdminExamListItem(BaseModel):
    """GET /api/admin/exams 列表项（含学生信息）"""
    id: int
    student_id: str
    student_name: str
    subject: str
    status: str
    question_count: int
    total_score: float
    obtained_score: float | None = None
    created_at: str
    submitted_at: str | None = None


class AdminExamListOut(BaseModel):
    total: int
    items: list[AdminExamListItem]


class AdminScoreUpdateRequest(BaseModel):
    """PUT /api/admin/exams/{id}/answers/{seq}/score 请求"""
    score: float
    reason: str | None = None


class AdminScoreUpdateResponse(BaseModel):
    seq: int
    score: float
    llm_reason: str | None = None
    obtained_score: float


# ========== v4.0 M3：学生记忆 ==========

class WrongQuestionListItem(BaseModel):
    id: int
    question_type: str | None = None
    stem: str | None = None
    options: dict | None = None
    materials: str | None = None
    sub_questions: list | None = None
    wrong_count: int
    mastered: int
    last_wrong_at: str
    knowledge_point_ids: list[str] = []
    subject: str


class PaginatedWrongQuestions(BaseModel):
    total: int
    items: list[WrongQuestionListItem]


class WrongQuestionRetryRequest(BaseModel):
    answer: str


class WrongQuestionRetryResponse(BaseModel):
    correct: bool
    correct_answer: str | None = None
    explanation: str | None = None
    mastered: int


class WeakKpItem(BaseModel):
    kp_id: str
    rate: float
    wrong_count: int


class RecentExamSummary(BaseModel):
    subject: str
    score: int
    total: int
    date: str | None = None


class ProfileOut(BaseModel):
    style_profile: str | None = None
    weak_kps: list[WeakKpItem] = []
    recent_exam: RecentExamSummary | None = None
    memory_enabled: bool


class HotWrongKpItem(BaseModel):
    kp_id: str
    wrong_count: int


class WrongStatsOut(BaseModel):
    total: int
    unmastered: int
    hot_wrong_kps: list[HotWrongKpItem] = []


class AdminStudentProfile(BaseModel):
    style_profile: str | None = None
    weak_kps: list[WeakKpItem] = []
    recent_exam: RecentExamSummary | None = None
    wrong_stats: WrongStatsOut


class AdminWrongStatItem(BaseModel):
    kp_id: str
    wrong_count: int
    student_count: int
