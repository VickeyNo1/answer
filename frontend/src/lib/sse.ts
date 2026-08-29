/**
 * SSE 流式请求封装
 * 用于 POST /api/chat 的流式响应处理
 */
import { getToken } from "./auth";
import type { KbRef } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface SSECallbacks {
  onStart?: (conversationId: number) => void;
  onDelta?: (content: string) => void;
  onDone?: (messageId: number) => void;
  /** status 仅在 HTTP 层错误时传入（如 429 配额用尽/队满），SSE error 事件不带 */
  onError?: (detail: string, status?: number) => void;
  onKbSearch?: () => void;
  onKpIds?: (kpIds: string[]) => void;
  // v4.0 新增事件
  onQueue?: (position: number) => void;
  onKbRefs?: (refs: KbRef[]) => void;
  onSuggestions?: (items: string[]) => void;
  /** 图片题目 OCR 识别结果（作答前下发） */
  onOcr?: (text: string) => void;
}

/**
 * 发送聊天消息并处理 SSE 流式响应
 */
export async function sendChatMessage(
  conversationId: number | null,
  message: string,
  subject: string | null,
  imageBase64: string | null,
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
      image_base64: imageBase64 || undefined,
    }),
  });

  if (res.status === 401) {
    callbacks.onError?.("登录已过期，请重新登录", 401);
    return;
  }

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "请求失败" }));
    // 429（配额用尽/排队已满）等错误携带状态码上抛，便于调用方区分展示
    callbacks.onError?.(error.detail || `请求失败 (${res.status})`, res.status);
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
          case "queue":
            callbacks.onQueue?.(data.position);
            break;
          case "kb_refs":
            callbacks.onKbRefs?.(data.refs);
            break;
          case "suggestions":
            callbacks.onSuggestions?.(data.items);
            break;
          case "ocr":
            callbacks.onOcr?.(data.text);
            break;
        }
      } catch {
        // 忽略解析失败的行
      }
    }
  }
}
