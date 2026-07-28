"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { apiGet, apiPost, apiDelete } from "@/lib/api";
import { getRole, clearAuth } from "@/lib/auth";
import { sendChatMessage } from "@/lib/sse";
import type { UserInfo, ConversationOut, MessageOut, Subject } from "@/types";
import { ConversationList } from "@/components/ConversationList";
import { ChatWindow } from "@/components/ChatWindow";
import { ChatInput } from "@/components/ChatInput";

export default function HomePage() {
  const router = useRouter();

  // 用户信息
  const [user, setUser] = useState<UserInfo | null>(null);
  const [role, setRole] = useState<string | null>(null);

  // 对话列表
  const [conversations, setConversations] = useState<ConversationOut[]>([]);
  const [loadingConversations, setLoadingConversations] = useState(true);

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

  // 错误提示
  const [error, setError] = useState("");

  // 初始化：获取用户信息和角色
  useEffect(() => {
    setRole(getRole());
    apiGet<UserInfo>("/api/auth/me")
      .then(setUser)
      .catch(() => {});
    apiGet<Subject[]>("/api/subjects")
      .then((data) => {
        setSubjects(data);
        // 默认选中首个已上线科目
        if (data.length > 0) setSelectedSubject(data[0].subject);
      })
      .catch(() => {});
  }, []);

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
      // 回显该对话的所属科目（为空则保持当前选择）
      const conv = conversations.find((c) => c.id === id);
      if (conv?.subject) setSelectedSubject(conv.subject);
      try {
        const data = await apiGet<MessageOut[]>(`/api/conversations/${id}`);
        setMessages(data);
      } catch (err) {
        setError(err instanceof Error ? err.message : "加载消息失败");
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
    setError("");
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
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "删除失败");
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
      streamingContentRef.current = "";

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

      await sendChatMessage(targetConversationId, message, selectedSubject || null, {
        onStart: (convId) => {
          // 如果是新对话，更新 currentId 并刷新列表
          if (targetConversationId === null) {
            setCurrentId(convId);
            loadConversations();
          }
        },
        onKbSearch: () => {
          setKbSearching(true);
        },
        onDelta: (content) => {
          setKbSearching(false);
          streamingContentRef.current += content;
          setStreamingContent((prev) => prev + content);
        },
        onDone: (messageId) => {
          // 将流式内容转为正式消息（用服务端返回的 message_id 作为唯一 key）
          const assistantMsg: MessageOut = {
            id: messageId,
            role: "assistant",
            content: streamingContentRef.current,
            created_at: new Date().toISOString(),
          };
          setMessages((prev) => [...prev, assistantMsg]);
          setStreamingContent("");
          streamingContentRef.current = "";
          setStreaming(false);
          setKbSearching(false);
          // 如果是新对话，刷新对话列表获取正确标题
          if (targetConversationId === null) {
            loadConversations();
          }
        },
        onError: (detail) => {
          setError(detail);
          setStreaming(false);
          setStreamingContent("");
          setKbSearching(false);
        },
      });
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
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-3">
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold text-gray-900">会计答疑智能体</h1>
          <div className="flex items-center gap-1.5">
            <span className="text-sm text-gray-400">科目</span>
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
        <div className="flex items-center gap-4">
          {user && (
            <span className="text-sm text-gray-500">
              {user.name}（{user.student_id}）
            </span>
          )}
          {role === "admin" && (
            <a
              href="/admin"
              className="rounded-lg px-3 py-1 text-sm text-blue-600 transition-colors hover:bg-blue-50"
            >
              管理后台
            </a>
          )}
          <button
            onClick={handleLogout}
            className="rounded-lg px-3 py-1 text-sm text-gray-500 transition-colors hover:bg-gray-100"
          >
            退出
          </button>
        </div>
      </header>

      {/* 错误提示 */}
      {error && (
        <div className="flex items-center justify-between bg-red-50 px-6 py-2 text-sm text-red-600">
          <span>{error}</span>
          <button onClick={() => setError("")} className="text-red-400 hover:text-red-600">
            ✕
          </button>
        </div>
      )}

      {/* 主内容区 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 左侧对话列表 */}
        <ConversationList
          conversations={conversations}
          currentId={currentId}
          onSelect={handleSelectConversation}
          onCreate={handleCreateConversation}
          onDelete={handleDeleteConversation}
          loading={loadingConversations}
        />

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
              />
              <ChatInput onSend={handleSendMessage} disabled={streaming} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}
