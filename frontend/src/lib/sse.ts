/**
 * SSE 流式请求封装
 * 用于 POST /api/chat 的流式响应处理
 */
import { getToken } from "./auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface SSECallbacks {
  onStart?: (conversationId: number) => void;
  onDelta?: (content: string) => void;
  onDone?: (messageId: number) => void;
  onError?: (detail: string) => void;
  onKbSearch?: () => void;
  onKpIds?: (kpIds: string[]) => void;
}

/**
 * 发送聊天消息并处理 SSE 流式响应
 */
export async function sendChatMessage(
  conversationId: number | null,
  message: string,
  subject: string | null,
  callbacks: SSECallbacks
): Promise<void> {
  const token = getToken();
  if (!token) {
    callbacks.onError?.("未登录");
    return;
  }

  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      conversation_id: conversationId,
      message,
      subject,
    }),
  });

  if (res.status === 401) {
    callbacks.onError?.("登录已过期，请重新登录");
    return;
  }

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "请求失败" }));
    callbacks.onError?.(error.detail || `请求失败 (${res.status})`);
    return;
  }

  const reader = res.body?.getReader();
  if (!reader) {
    callbacks.onError?.("无法读取响应流");
    return;
  }

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data: ")) continue;

      try {
        const data = JSON.parse(trimmed.slice(6));
        switch (data.type) {
          case "start":
            callbacks.onStart?.(data.conversation_id);
            break;
          case "delta":
            callbacks.onDelta?.(data.content);
            break;
          case "done":
            callbacks.onDone?.(data.message_id);
            break;
          case "error":
            callbacks.onError?.(data.detail);
            break;
          case "kb_search":
            callbacks.onKbSearch?.();
            break;
          case "kp_ids":
            callbacks.onKpIds?.(data.kp_ids);
            break;
        }
      } catch {
        // 忽略解析失败的行
      }
    }
  }
}
