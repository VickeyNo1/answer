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
}

// ========== 对话相关 ==========

export interface ChatRequest {
  conversation_id: number | null;
  message: string;
  subject_id?: number | null;
}

export interface ConversationOut {
  id: number;
  title: string;
  created_at: string;
  subject_id?: number | null;
}

export interface MessageOut {
  id: number;
  role: string;
  content: string;
  created_at: string;
}

// ========== 知识库相关 ==========

export interface DocumentInfo {
  name: string;
  chunk_count: number;
  created_at: string;
  subject_id?: number | null;
}

// ========== 科目相关 ==========

export interface Subject {
  id: number;
  name: string;
  category: string; // 'general' | 'professional'
  description: string;
  sort_order: number;
  created_at: string;
}

export interface SubjectCreate {
  name: string;
  category: string;
  description?: string;
  sort_order?: number;
}

export interface SubjectUpdate {
  name?: string;
  category?: string;
  description?: string;
  sort_order?: number;
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

export type SSEEvent =
  | SSEStartEvent
  | SSEDeltaEvent
  | SSEDoneEvent
  | SSEErrorEvent;
