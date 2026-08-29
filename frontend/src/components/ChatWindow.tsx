"use client";

import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { apiPost } from "@/lib/api";
import type { MessageOut, KbRef } from "@/types";

interface ChatWindowProps {
  messages: MessageOut[];
  streamingContent: string;
  streaming: boolean;
  kbSearching?: boolean;
  /** v4.0 排队位次（null=未排队） */
  queuePosition?: number | null;
  /** v4.0 流式过程中收到的引用（尚未落到消息上） */
  streamingKbRefs?: KbRef[];
  /** v4.0 各 assistant 消息的引用（key=message id） */
  kbRefsByMessage?: Record<number, KbRef[]>;
  /** v4.0 追问建议（最后一条回答之后展示） */
  suggestions?: string[];
  /** 图片题目 OCR 识别文本（作答前展示“已识别题目”） */
  ocrText?: string | null;
  onSuggestionClick?: (text: string) => void;
}

export function ChatWindow({
  messages,
  streamingContent,
  streaming,
  kbSearching,
  queuePosition,
  streamingKbRefs,
  kbRefsByMessage,
  suggestions,
  ocrText,
  onSuggestionClick,
}: ChatWindowProps) {
  const bottomRef = useRef<HTMLDivElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  // 本次会话内已提交的反馈（key=message id），已评过显示选中态
  const [feedbacks, setFeedbacks] = useState<Record<number, "up" | "down">>({});
  // 点踩理由弹窗对应的 message id（null=关闭）
  const [reasonForId, setReasonForId] = useState<number | null>(null);

  // 自动滚动到底部
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, streamingContent]);

  async function handleFeedback(messageId: number, rating: "up" | "down", reason?: string) {
    await apiPost("/api/feedback", { message_id: messageId, rating, reason });
    setFeedbacks((prev) => ({ ...prev, [messageId]: rating }));
  }

  const hasContent = messages.length > 0 || streaming;

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-y-auto bg-gray-50 px-4 py-6"
    >
      <div className="mx-auto max-w-3xl space-y-6">
        {!hasContent ? (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-blue-100">
              <svg className="h-8 w-8 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 3v-3z" />
              </svg>
            </div>
            <h3 className="text-lg font-medium text-gray-700">会计答疑智能体</h3>
            <p className="mt-1 text-sm text-gray-400">
              在下方输入你的会计问题，AI 将为你解答
            </p>
          </div>
        ) : (
          <>
            {messages.map((msg) => (
              <MessageBubble
                key={msg.id}
                message={msg}
                kbRefs={kbRefsByMessage?.[msg.id]}
                rating={feedbacks[msg.id]}
                onRate={(rating) => {
                  if (rating === "down") {
                    setReasonForId(msg.id);
                  } else {
                    handleFeedback(msg.id, "up").catch(() => {});
                  }
                }}
              />
            ))}

            {/* 追问建议按钮（非流式状态下展示在最后一条回答后） */}
            {!streaming && suggestions && suggestions.length > 0 && (
              <div className="flex flex-wrap gap-2 pl-9">
                {suggestions.map((s, i) => (
                  <button
                    key={i}
                    onClick={() => onSuggestionClick?.(s)}
                    className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1.5 text-left text-sm text-blue-700 transition-colors hover:bg-blue-100"
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}

            {/* 流式输出中的 AI 消息 */}
            {streaming && (
              <div className="flex justify-start">
                <div className="max-w-[80%] rounded-2xl rounded-tl-sm bg-white px-4 py-3 shadow-sm ring-1 ring-gray-200">
                  {queuePosition != null && !streamingContent && (
                    <div className="mb-1 flex items-center gap-1.5 text-xs text-amber-600">
                      <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      <span>当前提问人数较多，排队中（第 {queuePosition} 位）…</span>
                    </div>
                  )}
                  {ocrText && !streamingContent && (
                    <div className="mb-1 flex items-center gap-1.5 text-xs text-green-600">
                      <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      <span>
                        已识别题目，正在作答…
                        <span className="ml-1 text-gray-400">{ocrText.slice(0, 40)}{ocrText.length > 40 ? "…" : ""}</span>
                      </span>
                    </div>
                  )}
                  {kbSearching && !streamingContent && (
                    <div className="mb-1 flex items-center gap-1.5 text-xs text-blue-500">
                      <svg className="h-3.5 w-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      <span>正在检索知识库…</span>
                    </div>
                  )}
                  {streamingKbRefs && streamingKbRefs.length > 0 && (
                    <KbRefsCard refs={streamingKbRefs} />
                  )}
                  {streamingContent ? (
                    <div className="prose prose-chat max-w-none">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>
                        {streamingContent}
                      </ReactMarkdown>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1 py-1">
                      <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.3s]"></span>
                      <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:-0.15s]"></span>
                      <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400"></span>
                    </div>
                  )}
                </div>
              </div>
            )}
          </>
        )}
        <div ref={bottomRef} />
      </div>

      {/* 点踩理由弹窗（理由必填） */}
      {reasonForId !== null && (
        <FeedbackReasonModal
          onClose={() => setReasonForId(null)}
          onSubmit={async (reason) => {
            await handleFeedback(reasonForId, "down", reason);
            setReasonForId(null);
          }}
        />
      )}
    </div>
  );
}

/** 单条消息气泡 */
function MessageBubble({
  message,
  kbRefs,
  rating,
  onRate,
}: {
  message: MessageOut;
  kbRefs?: KbRef[];
  rating?: "up" | "down";
  onRate: (rating: "up" | "down") => void;
}) {
  const isUser = message.role === "user";

  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className="flex items-start gap-2 max-w-[80%]">
        {!isUser && (
          <div className="mt-1 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-blue-100">
            <span className="text-xs font-medium text-blue-600">AI</span>
          </div>
        )}
        <div
          className={`rounded-2xl px-4 py-3 shadow-sm ${
            isUser
              ? "rounded-tr-sm bg-blue-600 text-white"
              : "rounded-tl-sm bg-white text-gray-800 ring-1 ring-gray-200"
          }`}
        >
          {isUser ? (
            <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
              {message.content}
            </p>
          ) : (
            <>
              {kbRefs && kbRefs.length > 0 && <KbRefsCard refs={kbRefs} />}
              <div className="prose prose-chat max-w-none">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {message.content}
                </ReactMarkdown>
              </div>
              {/* 👍/👎 反馈按钮（已评过显示选中态，可再点覆盖更新） */}
              <div className="mt-2 flex items-center gap-1 border-t border-gray-100 pt-1.5">
                <button
                  onClick={() => onRate("up")}
                  title="有帮助"
                  className={`rounded-md px-1.5 py-0.5 text-sm transition-colors ${
                    rating === "up"
                      ? "bg-blue-50 text-blue-600"
                      : "text-gray-300 hover:bg-gray-100 hover:text-gray-500"
                  }`}
                >
                  👍
                </button>
                <button
                  onClick={() => onRate("down")}
                  title="没帮助"
                  className={`rounded-md px-1.5 py-0.5 text-sm transition-colors ${
                    rating === "down"
                      ? "bg-red-50 text-red-500"
                      : "text-gray-300 hover:bg-gray-100 hover:text-gray-500"
                  }`}
                >
                  👎
                </button>
              </div>
            </>
          )}
        </div>
        {isUser && (
          <div className="mt-1 flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-blue-600">
            <span className="text-xs font-medium text-white">我</span>
          </div>
        )}
      </div>
    </div>
  );
}

/** 知识库引用卡片（可展开查看摘要） */
function KbRefsCard({ refs }: { refs: KbRef[] }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mb-2 overflow-hidden rounded-lg border border-blue-100 bg-blue-50/50">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-1.5 text-xs text-blue-600 hover:bg-blue-50"
      >
        <span className="flex items-center gap-1">
          <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6.253v13m0-13C10.832 5.477 9.246 5 7.5 5S4.168 5.477 3 6.253v13C4.168 18.477 5.754 18 7.5 18s3.332.477 4.5 1.253m0-13C13.168 5.477 14.754 5 16.5 5c1.747 0 3.332.477 4.5 1.253v13C19.832 18.477 18.247 18 16.5 18c-1.746 0-3.332.477-4.5 1.253" />
          </svg>
          引用教材 {refs.length} 处
        </span>
        <svg
          className={`h-3.5 w-3.5 transition-transform ${expanded ? "rotate-180" : ""}`}
          fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
        </svg>
      </button>
      {expanded && (
        <div className="space-y-2 border-t border-blue-100 px-3 py-2">
          {refs.map((ref, i) => (
            <div key={`${ref.kp_id}-${i}`} className="text-xs">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="rounded bg-blue-100 px-1.5 py-0.5 font-mono text-blue-700">
                  [{i + 1}] {ref.kp_id}
                </span>
                <span className="text-gray-500">{ref.chapter}</span>
                <span className="font-medium text-gray-700">{ref.title}</span>
              </div>
              <p className="mt-0.5 text-gray-500">{ref.snippet}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** 点踩理由弹窗（理由必填） */
function FeedbackReasonModal({
  onClose,
  onSubmit,
}: {
  onClose: () => void;
  onSubmit: (reason: string) => Promise<void>;
}) {
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = reason.trim();
    if (!trimmed) return;
    setSubmitting(true);
    setError("");
    try {
      await onSubmit(trimmed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-900">哪里没答好？</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="请填写点踩理由（必填），帮助我们改进答案质量"
            rows={3}
            autoFocus
            className="w-full resize-none rounded-lg border border-gray-300 px-4 py-2.5 text-sm text-gray-900 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            required
          />
          {error && (
            <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">{error}</div>
          )}
          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
            >
              取消
            </button>
            <button
              type="submit"
              disabled={submitting || !reason.trim()}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {submitting ? "提交中..." : "提交"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
