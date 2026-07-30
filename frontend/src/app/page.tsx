"use client";

import { useState, useEffect, useCallback, useRef, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { apiGet, apiDelete } from "@/lib/api";
import { getRole, clearAuth } from "@/lib/auth";
import { sendChatMessage } from "@/lib/sse";
import type { UserInfo, ConversationOut, MessageOut, Subject, KbRef } from "@/types";
import { ConversationList } from "@/components/ConversationList";
import { ChatWindow } from "@/components/ChatWindow";
import { ChatInput } from "@/components/ChatInput";
import { ChangePasswordModal } from "@/components/ChangePasswordModal";

export default function HomePage() {
  return (
    <Suspense fallback={null}>
      <HomeContent />
    </Suspense>
  );
}

function HomeContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const prefillAsk = searchParams.get("ask") || "";
  const prefillSubject = searchParams.get("subject") || "";

  // 用户信息
  const [user, setUser] = useState<UserInfo | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [showPasswordModal, setShowPasswordModal] = useState(false);

  // 对话列表
  const [conversations, setConversations] = useState<ConversationOut[]>([]);
  const [loadingConversations, setLoadingConversations] = useState(true);
  // 移动端抽屉开关（<768px 时会话列表以抽屉呈现）
  const [drawerOpen, setDrawerOpen] = useState(false);

  // 当前对话
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [messages, setMessages] = useState<MessageOut[]>([]);
  const [loadingMessages, setLoadingMessages] = useState(false);

  // 科目（枚举由知识库侧维护，/api/subjects 仅返回已上线项，必选）
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [selectedSubject, setSelectedSubject] = useState<string>("");

  // 流式状态
  const [streaming, setStreaming] = useState(false);
  const [streamingContent, setStreamingContent] = useState("");
  const [kbSearching, setKbSearching] = useState(false);
  // 用 ref 累积流式内容，避免在状态更新函数中嵌套调用 setMessages
  const streamingContentRef = useRef("");

  // v4.0 新事件状态：排队位次 / 流式引用 / 各消息引用 / 追问建议
  const [queuePosition, setQueuePosition] = useState<number | null>(null);
  const [streamingKbRefs, setStreamingKbRefs] = useState<KbRef[]>([]);
  const streamingKbRefsRef = useRef<KbRef[]>([]);
  const [kbRefsByMessage, setKbRefsByMessage] = useState<Record<number, KbRef[]>>({});
  const [suggestions, setSuggestions] = useState<string[]>([]);

  // 错误提示（kind 区分普通错误与 429 配额/排队提示）
  const [error, setError] = useState("");
  const [errorKind, setErrorKind] = useState<"error" | "quota">("error");

  // 初始化：获取用户信息和角色
  useEffect(() => {
    setRole(getRole());
    apiGet<UserInfo>("/api/auth/me")
      .then(setUser)
      .catch(() => {});
    apiGet<Subject[]>("/api/subjects")
      .then((data) => {
        setSubjects(data);
        // 默认选中首个已上线科目；URL ?subject= 优先预填
        if (prefillSubject && data.some((s) => s.subject === prefillSubject)) {
          setSelectedSubject(prefillSubject);
        } else if (data.length > 0) {
          setSelectedSubject(data[0].subject);
        }
      })
      .catch(() => {});
  }, [prefillSubject]);

  // 初始化：加载对话列表
  const loadConversations = useCallback(async () => {
    setLoadingConversations(true);
    try {
      const data = await apiGet<ConversationOut[]>("/api/conversations");
      setConversations(data);
    } catch {
      // 忽略错误
    } finally {
      setLoadingConversations(false);
    }
  }, []);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  // 选择对话：加载消息历史
  const handleSelectConversation = useCallback(
    async (id: number) => {
      setCurrentId(id);
      setLoadingMessages(true);
      setMessages([]);
      setSuggestions([]);
      setDrawerOpen(false);
      // 回显该对话的所属科目（为空则保持当前选择）
      const conv = conversations.find((c) => c.id === id);
      if (conv?.subject) setSelectedSubject(conv.subject);
      try {
        const data = await apiGet<MessageOut[]>(`/api/conversations/${id}`);
        setMessages(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载消息失败");
        setErrorKind("error");
      } finally {
        setLoadingMessages(false);
      }
    },
    [conversations]
  );

  // 新建对话
  const handleCreateConversation = useCallback(() => {
    setCurrentId(null);
    setMessages([]);
    setSuggestions([]);
    setError("");
    setDrawerOpen(false);
  }, []);

  // 删除对话
  const handleDeleteConversation = useCallback(
    async (id: number) => {
      try {
        await apiDelete(`/api/conversations/${id}`);
        setConversations((prev) => prev.filter((c) => c.id !== id));
        if (currentId === id) {
          setCurrentId(null);
          setMessages([]);
          setSuggestions([]);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "删除失败");
        setErrorKind("error");
      }
    },
    [currentId]
  );

  // 发送消息（SSE 流式）
  const handleSendMessage = useCallback(
    async (message: string) => {
      setError("");
      setStreaming(true);
      setStreamingContent("");
      setKbSearching(false);
      setQueuePosition(null);
      setStreamingKbRefs([]);
      setSuggestions([]);
      streamingContentRef.current = "";
      streamingKbRefsRef.current = [];

      // 先把用户消息追加到列表
      const tempUserMsg: MessageOut = {
        id: Date.now(),
        role: "user",
        content: message,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, tempUserMsg]);

      // 保存当前的 conversationId（可能为 null）
      const targetConversationId = currentId;

      try {
        await sendChatMessage(targetConversationId, message, selectedSubject || null, {
          onStart: (convId) => {
            // 如果是新对话，更新 currentId 并刷新列表
            if (targetConversationId === null) {
              setCurrentId(convId);
              loadConversations();
            }
          },
          onQueue: (position) => {
            setQueuePosition(position);
          },
          onKbSearch: () => {
            setQueuePosition(null);
            setKbSearching(true);
          },
          onKbRefs: (refs) => {
            streamingKbRefsRef.current = refs;
            setStreamingKbRefs(refs);
          },
          onSuggestions: (items) => {
            setSuggestions(items);
          },
          onDelta: (content) => {
            setKbSearching(false);
            setQueuePosition(null);
            streamingContentRef.current += content;
            setStreamingContent((prev) => prev + content);
          },
          onDone: (messageId) => {
            // messageId=0 表示后端未落库任何回答（仅结束流），不追加幽灵消息
            if (messageId !== 0) {
              // 将流式内容转为正式消息（用服务端返回的 message_id 作为唯一 key）
              const assistantMsg: MessageOut = {
                id: messageId,
                role: "assistant",
                content: streamingContentRef.current,
                created_at: new Date().toISOString(),
              };
              setMessages((prev) => [...prev, assistantMsg]);
              // 引用落到该条消息上
              if (streamingKbRefsRef.current.length > 0) {
                const refs = streamingKbRefsRef.current;
                setKbRefsByMessage((prev) => ({ ...prev, [messageId]: refs }));
              }
            }
            setStreamingContent("");
            streamingContentRef.current = "";
            streamingKbRefsRef.current = [];
            setStreamingKbRefs([]);
            setStreaming(false);
            setKbSearching(false);
            setQueuePosition(null);
            // 如果是新对话，刷新对话列表获取正确标题
            if (targetConversationId === null) {
              loadConversations();
            }
          },
          onError: (detail, status) => {
            setError(detail);
            // 429：配额用尽/排队已满/回答进行中，展示友好提示（后端 detail 已分档）
            setErrorKind(status === 429 ? "quota" : "error");
            setStreaming(false);
            setStreamingContent("");
            setKbSearching(false);
            setQueuePosition(null);
            setStreamingKbRefs([]);
            streamingKbRefsRef.current = [];
          },
        });
      } catch (e) {
        // 网络级异常（fetch 抛错等非 HTTP 错误路径）：提示并完整重置流式状态，避免输入框永久禁用
        setError(e instanceof Error ? e.message : "请求失败，请稍后重试");
        setErrorKind("error");
        setStreaming(false);
        setStreamingContent("");
        streamingContentRef.current = "";
        setKbSearching(false);
        setQueuePosition(null);
        setStreamingKbRefs([]);
        streamingKbRefsRef.current = [];
      }
    },
    [currentId, loadConversations, selectedSubject]
  );

  function handleLogout() {
    clearAuth();
    router.replace("/login");
  }

  return (
    <div className="flex h-screen flex-col bg-gray-50">
      {/* 顶栏 */}
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-3 py-3 md:px-6">
        <div className="flex items-center gap-2 md:gap-3">
          {/* 移动端：汉堡键唤出会话列表抽屉 */}
          <button
            onClick={() => setDrawerOpen(true)}
            className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100 md:hidden"
            title="会话列表"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <h1 className="text-lg font-semibold text-gray-900 max-md:hidden">会计答疑智能体</h1>
          <div className="flex items-center gap-1.5">
            <span className="text-sm text-gray-400 max-md:hidden">科目</span>
            <select
              value={selectedSubject}
              onChange={(e) => setSelectedSubject(e.target.value)}
              className="rounded-lg border border-gray-300 px-3 py-1 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            >
              {subjects.map((s) => (
                <option key={s.subject} value={s.subject}>{s.name}</option>
              ))}
            </select>
          </div>
        </div>
        <div className="flex items-center gap-2 md:gap-4">
          {/* 个人菜单（修改密码入口） */}
          {user && (
            <div className="relative">
              <button
                onClick={() => setUserMenuOpen((v) => !v)}
                className="flex items-center gap-1 rounded-lg px-2 py-1 text-sm text-gray-500 transition-colors hover:bg-gray-100"
              >
                <span className="max-w-[8rem] truncate">
                  {user.name}
                  <span className="max-md:hidden">（{user.student_id}）</span>
                </span>
                <svg className="h-3.5 w-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {userMenuOpen && (
                <>
                  <div
                    className="fixed inset-0 z-10"
                    onClick={() => setUserMenuOpen(false)}
                  />
                  <div className="absolute right-0 top-full z-20 mt-1 w-32 rounded-lg border border-gray-200 bg-white py-1 shadow-lg">
                    <button
                      onClick={() => {
                        setUserMenuOpen(false);
                        setShowPasswordModal(true);
                      }}
                      className="block w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                    >
                      修改密码
                    </button>
                    <button
                      onClick={handleLogout}
                      className="block w-full px-4 py-2 text-left text-sm text-gray-700 hover:bg-gray-50"
                    >
                      退出登录
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
          {role === "admin" && (
            <a
              href="/admin"
              className="rounded-lg px-3 py-1 text-sm text-blue-600 transition-colors hover:bg-blue-50 max-md:hidden"
            >
              管理后台
            </a>
          )}
          <a
            href="/exam"
            className="rounded-lg bg-blue-50 px-3 py-1 text-sm text-blue-600 transition-colors hover:bg-blue-100"
          >
            去考试
          </a>
        </div>
      </header>

      {/* 错误提示（quota=429 配额/排队提示，用琥珀色区分） */}
      {error && (
        <div
          className={`flex items-center justify-between px-4 py-2 text-sm md:px-6 ${
            errorKind === "quota"
              ? "bg-amber-50 text-amber-700"
              : "bg-red-50 text-red-600"
          }`}
        >
          <span>{error}</span>
          <button
            onClick={() => setError("")}
            className={errorKind === "quota" ? "text-amber-400 hover:text-amber-600" : "text-red-400 hover:text-red-600"}
          >
            ✕
          </button>
        </div>
      )}

      {/* 主内容区 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 左侧对话列表（桌面端常驻） */}
        <div className="hidden md:flex">
          <ConversationList
            conversations={conversations}
            currentId={currentId}
            onSelect={handleSelectConversation}
            onCreate={handleCreateConversation}
            onDelete={handleDeleteConversation}
            loading={loadingConversations}
          />
        </div>

        {/* 移动端抽屉（汉堡键唤出 + 遮罩） */}
        {drawerOpen && (
          <div className="fixed inset-0 z-40 md:hidden">
            <div
              className="absolute inset-0 bg-black/30"
              onClick={() => setDrawerOpen(false)}
            />
            <div className="absolute inset-y-0 left-0 flex shadow-xl">
              <ConversationList
                conversations={conversations}
                currentId={currentId}
                onSelect={handleSelectConversation}
                onCreate={handleCreateConversation}
                onDelete={handleDeleteConversation}
                loading={loadingConversations}
              />
            </div>
          </div>
        )}

        {/* 右侧聊天区 */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {loadingMessages ? (
            <div className="flex flex-1 items-center justify-center">
              <p className="text-gray-400">加载消息中...</p>
            </div>
          ) : (
            <>
              <ChatWindow
                messages={messages}
                streamingContent={streamingContent}
                streaming={streaming}
                kbSearching={kbSearching}
                queuePosition={queuePosition}
                streamingKbRefs={streamingKbRefs}
                kbRefsByMessage={kbRefsByMessage}
                suggestions={suggestions}
                onSuggestionClick={handleSendMessage}
              />
              <ChatInput onSend={handleSendMessage} disabled={streaming} initialValue={prefillAsk} />
            </>
          )}
        </div>
      </div>

      {/* 修改密码弹窗 */}
      {showPasswordModal && (
        <ChangePasswordModal onClose={() => setShowPasswordModal(false)} />
      )}
    </div>
  );
}
