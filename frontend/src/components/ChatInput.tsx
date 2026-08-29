"use client";

import { useState, useRef, useEffect } from "react";
import { compressImage } from "@/lib/image";

interface ChatInputProps {
  onSend: (message: string, imageBase64?: string | null) => void;
  disabled?: boolean;
  placeholder?: string;
  initialValue?: string;
  /** 图片压缩/读取失败时的提示回调 */
  onImageError?: (detail: string) => void;
}

export function ChatInput({ onSend, disabled, placeholder, initialValue, onImageError }: ChatInputProps) {
  const [text, setText] = useState(initialValue || "");
  // 待发送的图片：压缩后的纯 base64 + 本地预览 URL（发送后释放）
  const [imageBase64, setImageBase64] = useState<string | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [imageLoading, setImageLoading] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // 自适应高度
  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 200) + "px";
  }, [text]);

  // 组件卸载时释放预览 Object URL，避免 blob 泄漏
  useEffect(() => {
    return () => {
      if (imagePreview) URL.revokeObjectURL(imagePreview);
    };
  }, [imagePreview]);

  function handleSubmit() {
    const trimmed = text.trim();
    if (disabled || (!trimmed && !imageBase64)) return;
    onSend(trimmed, imageBase64);
    setText("");
    clearImage();
  }

  function clearImage() {
    if (imagePreview) URL.revokeObjectURL(imagePreview);
    setImageBase64(null);
    setImagePreview(null);
  }

  async function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    // 重置输入框，允许重复选择同一文件
    e.target.value = "";
    if (!file) return;
    if (!file.type.startsWith("image/")) {
      onImageError?.("请选择图片文件");
      return;
    }
    setImageLoading(true);
    try {
      const b64 = await compressImage(file);
      clearImage();
      setImageBase64(b64);
      setImagePreview(URL.createObjectURL(file));
    } catch (err) {
      onImageError?.(err instanceof Error ? err.message : "图片处理失败");
    } finally {
      setImageLoading(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    // Enter 发送，Shift+Enter 换行
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  }

  return (
    <div className="border-t border-gray-200 bg-white px-4 py-3">
      <div className="mx-auto max-w-3xl">
        {/* 图片预览（可移除） */}
        {(imagePreview || imageLoading) && (
          <div className="mb-2 flex items-center gap-2">
            {imageLoading ? (
              <span className="text-xs text-gray-400">图片处理中…</span>
            ) : (
              <>
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={imagePreview || undefined}
                  alt="题目图片预览"
                  className="h-16 w-16 rounded-lg border border-gray-200 object-cover"
                />
                <span className="text-xs text-gray-400">发送后将自动识别图中题目</span>
                <button
                  onClick={clearImage}
                  className="text-xs text-red-400 hover:text-red-600"
                  title="移除图片"
                >
                  ✕ 移除
                </button>
              </>
            )}
          </div>
        )}
        <div className="flex items-end gap-2">
          {/* 上传图片按钮（隐藏 file input） */}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            className="hidden"
            onChange={handleFileChange}
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || imageLoading}
            className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl border border-gray-300 text-gray-500 transition-colors hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-50"
            title="上传题目图片"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13"
              />
            </svg>
          </button>
          <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder || "输入你的会计问题... (Enter 发送, Shift+Enter 换行)"}
          rows={1}
          disabled={disabled}
          className="flex-1 resize-none rounded-xl border border-gray-300 px-4 py-2.5 text-sm text-gray-900 outline-none transition-colors focus:border-blue-500 focus:ring-2 focus:ring-blue-200 disabled:cursor-not-allowed disabled:opacity-50"
          style={{ maxHeight: "200px" }}
          />
        <button
          onClick={handleSubmit}
          disabled={disabled || (!text.trim() && !imageBase64)}
          className="flex h-11 w-11 flex-shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white transition-colors hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
          title="发送"
        >
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"
            />
          </svg>
        </button>
        </div>
      </div>
    </div>
  );
}
