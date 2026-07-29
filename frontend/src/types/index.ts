// ========== 认证相关 ==========

export interface LoginRequest {
  student_id: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  role: string;
}

export interface UserInfo {
  id: number;
  student_id: string;
  name: string;
  role: string;
  created_at: string;
  // v4.0 权益覆盖值（null=跟随全局默认）
  daily_question_limit?: number | null;
  memory_enabled?: boolean | null;
}

// v4.0 学生自助改密码
export interface PasswordChangeRequest {
  old_password: string;
  new_password: string;
}

// ========== 对话相关 ==========

export interface ChatRequest {
  conversation_id: number | null;
  message: string;
  subject?: string | null;
}

export interface ConversationOut {
  id: number;
  title: string;
  created_at: string;
  subject?: string | null;
}

export interface MessageOut {
  id: number;
  role: string;
  content: string;
  created_at: string;
}

// ========== 科目相关（枚举由知识库侧维护） ==========

export interface Subject {
  subject: string;
  name: string;
  status: string; // 'online' | 'offline' | 'planned'
}

// ========== 大模型管理相关 ==========

export interface ModelConfig {
  id: number;
  provider: string; // 'ali' | 'deepseek'
  model_name: string;
  display_name: string;
  price_in: number;
  price_out: number;
  enabled: boolean;
  is_active: boolean;
  created_at: string;
}

export interface ModelConfigCreate {
  provider: string;
  model_name: string;
  display_name: string;
  price_in: number;
  price_out: number;
  enabled?: boolean;
}

export interface ModelConfigUpdate {
  provider?: string;
  model_name?: string;
  display_name?: string;
  price_in?: number;
  price_out?: number;
  enabled?: boolean;
}

export interface UsageByModel {
  model_name: string;
  tokens: number;
  cost: number;
}

export interface UsageDaily {
  date: string;
  tokens: number;
  cost: number;
}

export interface UsageStats {
  total_tokens: number;
  total_cost: number;
  today_tokens: number;
  today_cost: number;
  by_model: UsageByModel[];
  daily: UsageDaily[];
}

// ========== 管理员相关 ==========

export interface StudentCreate {
  student_id: string;
  name: string;
  password: string;
}

export interface StudentUpdate {
  name?: string;
  password?: string;
}

export interface StatsResponse {
  total_students: number;
  total_conversations: number;
  today_active_users: number;
}

export interface PaginatedStudents {
  items: UserInfo[];
  total: number;
  page: number;
  size: number;
}

export interface BatchImportResult {
  success: number;
  failed: number;
  errors: {
    row: number;
    student_id: string;
    reason: string;
  }[];
}

// ========== v4.0 M1：反馈相关 ==========

export interface FeedbackCreate {
  message_id: number;
  rating: "up" | "down";
  reason?: string;
}

export interface FeedbackItem {
  id: number;
  rating: "up" | "down";
  reason: string | null;
  student_id: string;
  student_name: string;
  question: string | null;
  answer: string;
  knowledge_point_ids: string[];
  created_at: string;
}

export interface PaginatedFeedbacks {
  total: number;
  items: FeedbackItem[];
}

// ========== v4.0 M1：检索质量报表 ==========

export interface KbStatsByDay {
  date: string;
  total: number;
  empty: number;
  degraded: number;
}

export interface KbStats {
  total: number;
  empty_count: number;
  empty_rate: number;
  degraded_count: number;
  avg_elapsed_ms: number;
  by_day: KbStatsByDay[];
  by_status: Record<string, number>;
}

export interface HotKp {
  kp_id: string;
  count: number;
}

// ========== v4.0 M1：全局设置与学生权益 ==========

export interface AppSettings {
  daily_question_limit_default: number;
  memory_enabled_default: boolean;
  chat_concurrency: number;
  chat_queue_size: number;
  profile_update_interval: number;
}

export type AppSettingsUpdate = Partial<AppSettings>;

export interface Entitlements {
  daily_question_limit: number | null;
  memory_enabled: boolean | null;
}

// ========== v4.0 M1：知识库引用 ==========

export interface KbRef {
  kp_id: string;
  chapter: string;
  title: string;
  snippet: string;
}

// ========== SSE 事件类型 ==========

export interface SSEStartEvent {
  type: "start";
  conversation_id: number;
}

export interface SSEDeltaEvent {
  type: "delta";
  content: string;
}

export interface SSEDoneEvent {
  type: "done";
  message_id: number;
}

export interface SSEErrorEvent {
  type: "error";
  detail: string;
}

export interface SSEKbSearchEvent {
  type: "kb_search";
}

export interface SSEKpIdsEvent {
  type: "kp_ids";
  kp_ids: string[];
}

// v4.0 新增：排队事件（入队推一次，每前进一位再推一次）
export interface SSEQueueEvent {
  type: "queue";
  position: number;
}

// v4.0 新增：知识库引用事件（检索命中后推送）
export interface SSEKbRefsEvent {
  type: "kb_refs";
  refs: KbRef[];
}

// v4.0 新增：追问建议事件（正文结束后、done 之前推送）
export interface SSESuggestionsEvent {
  type: "suggestions";
  items: string[];
}

export type SSEEvent =
  | SSEStartEvent
  | SSEDeltaEvent
  | SSEDoneEvent
  | SSEErrorEvent
  | SSEKbSearchEvent
  | SSEKpIdsEvent
  | SSEQueueEvent
  | SSEKbRefsEvent
  | SSESuggestionsEvent;
