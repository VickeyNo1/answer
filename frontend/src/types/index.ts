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

export type SSEEvent =
  | SSEStartEvent
  | SSEDeltaEvent
  | SSEDoneEvent
  | SSEErrorEvent
  | SSEKbSearchEvent
  | SSEKpIdsEvent;
