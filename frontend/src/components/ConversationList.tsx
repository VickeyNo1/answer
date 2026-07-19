"use client";

import { useState } from "react";
import type { ConversationOut } from "@/types";

interface ConversationListProps {
  conversations: ConversationOut[];
  currentId: number | null;
  onSelect: (id: number) => void;
  onCreate: () => void;
  onDelete: (id: number) => void;
  loading?: boolean;
}

export function ConversationList({
  conversations,
  currentId,
  onSelect,
  onCreate,
  onDelete,
  loading,
}: ConversationListProps) {
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  function handleDelete(e: React.MouseEvent, id: number) {
    e.stopPropagation();
    if (confirmDeleteId === id) {
      onDelete(id);
      setConfirmDeleteId(null);
    } else {
      setConfirmDeleteId(id);
    }
  }

  return (
    <aside className="flex w-64 flex-col border-r border-gray-200 bg-white">
      {/* 新建对话按钮 */}
      <div className="p-3">
        <button
          onClick={onCreate}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700"
        >
          <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
          </svg>
          新建对话
        </button>
      </div>

      {/* 对话列表 */}
      <div className="flex-1 overflow-y-auto px-2 pb-2">
        {loading ? (
          <p className="px-2 py-4 text-center text-sm text-gray-400">加载中...</p>
        ) : conversations.length === 0 ? (
          <p className="px-2 py-4 text-center text-sm text-gray-400">
            暂无对话，点击上方按钮开始
          </p>
        ) : (
          <div className="space-y-1">
            {conversations.map((conv) => (
              <div
                key={conv.id}
                onClick={() => onSelect(conv.id)}
                className={`group flex cursor-pointer items-center justify-between rounded-lg px-3 py-2.5 text-sm transition-colors ${
                  currentId === conv.id
                    ? "bg-blue-50 text-blue-700"
                    : "text-gray-700 hover:bg-gray-100"
                }`}
              >
                <span className="flex-1 truncate">{conv.title}</span>
                <button
                  onClick={(e) => handleDelete(e, conv.id)}
                  className={`ml-2 flex-shrink-0 transition-opacity ${
                    confirmDeleteId === conv.id
                      ? "text-red-500 opacity-100"
                      : "text-gray-400 opacity-0 group-hover:opacity-100"
                  } hover:text-red-600`}
                  title={confirmDeleteId === conv.id ? "再点一次确认删除" : "删除对话"}
                >
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      strokeWidth={2}
                      d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                    />
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}
      </div>
    </aside>
  );
}
