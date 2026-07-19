"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { apiGet, apiDelete, apiUpload } from "@/lib/api";
import type { DocumentInfo, Subject } from "@/types";

export function KnowledgeTab() {
  const [documents, setDocuments] = useState<DocumentInfo[]>([]);
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [selectedSubjectId, setSelectedSubjectId] = useState<number>(0);
  const [filterSubjectId, setFilterSubjectId] = useState<number>(-1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [dragOver, setDragOver] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<DocumentInfo[]>("/api/knowledge/documents");
      setDocuments(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadSubjects = useCallback(async () => {
    try {
      const data = await apiGet<Subject[]>("/api/subjects");
      setSubjects(data);
    } catch {
      // 忽略，不影响上传
    }
  }, []);

  useEffect(() => {
    loadDocuments();
    loadSubjects();
  }, [loadDocuments, loadSubjects]);

  const subjectName = useCallback(
    (id?: number | null): string => {
      if (!id) return "未分类";
      return subjects.find((s) => s.id === id)?.name || "未分类";
    },
    [subjects]
  );

  const filteredDocuments =
    filterSubjectId === -1
      ? documents
      : documents.filter((d) => (d.subject_id || 0) === filterSubjectId);

  async function handleUpload(file: File) {
    // 校验格式
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!ext || !["pdf", "docx", "txt"].includes(ext)) {
      setError("不支持的文件格式，仅支持 .pdf、.docx、.txt");
      return;
    }
    // 校验大小
    if (file.size > 10 * 1024 * 1024) {
      setError("文件大小超过限制（最大 10MB）");
      return;
    }

    setUploading(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      if (selectedSubjectId > 0) {
        formData.append("subject_id", String(selectedSubjectId));
      }
      await apiUpload<DocumentInfo>("/api/knowledge/upload", formData);
      loadDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleUpload(file);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleUpload(file);
  }

  async function handleDelete(name: string) {
    try {
      await apiDelete(`/api/knowledge/documents/${encodeURIComponent(name)}`);
      setConfirmDelete(null);
      loadDocuments();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  }

  return (
    <div className="space-y-4">
      {/* 错误提示 */}
      {error && (
        <div className="flex items-center justify-between rounded-xl bg-red-50 px-4 py-2.5 text-sm text-red-600">
          <span>{error}</span>
          <button onClick={() => setError("")} className="text-red-400 hover:text-red-600">✕</button>
        </div>
      )}

      {/* 科目选择（上传时归属） */}
      <div className="flex items-center gap-2">
        <label className="text-sm font-medium text-gray-700">上传归属科目：</label>
        <select
          value={selectedSubjectId}
          onChange={(e) => setSelectedSubjectId(Number(e.target.value))}
          className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
        >
          <option value={0}>未分类</option>
          {subjects.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
        <span className="text-xs text-gray-400">上传前请先选择该文档所属科目</span>
      </div>

      {/* 上传区域 */}
      <div
        onClick={() => fileInputRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={`cursor-pointer rounded-xl border-2 border-dashed p-8 text-center transition-colors ${
          dragOver
            ? "border-blue-500 bg-blue-50"
            : "border-gray-300 bg-white hover:border-blue-400 hover:bg-gray-50"
        }`}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".pdf,.docx,.txt"
          onChange={handleFileSelect}
          className="hidden"
        />
        {uploading ? (
          <div className="flex flex-col items-center gap-2">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent"></div>
            <p className="text-sm text-gray-500">正在上传并处理文档...</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2">
            <svg className="h-10 w-10 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            <p className="text-sm font-medium text-gray-700">
              点击或拖拽文件到此处上传
            </p>
            <p className="text-xs text-gray-400">
              支持 .pdf、.docx、.txt 格式，最大 10MB
            </p>
          </div>
        )}
      </div>

      {/* 文档列表 */}
      <div className="flex items-center gap-2">
        <label className="text-sm text-gray-500">按科目筛选：</label>
        <select
          value={filterSubjectId}
          onChange={(e) => setFilterSubjectId(Number(e.target.value))}
          className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
        >
          <option value={-1}>全部</option>
          <option value={0}>未分类</option>
          {subjects.map((s) => (
            <option key={s.id} value={s.id}>{s.name}</option>
          ))}
        </select>
      </div>
      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50 text-left text-gray-500">
              <th className="px-4 py-3 font-medium">文件名</th>
              <th className="px-4 py-3 font-medium">所属科目</th>
              <th className="px-4 py-3 font-medium">切片数</th>
              <th className="px-4 py-3 font-medium">上传时间</th>
              <th className="px-4 py-3 font-medium text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-400">加载中...</td>
              </tr>
            ) : filteredDocuments.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-gray-400">
                  暂无知识库文档，请上传文件
                </td>
              </tr>
            ) : (
              filteredDocuments.map((doc) => (
                <tr key={doc.name} className="border-b border-gray-100 last:border-0 hover:bg-gray-50">
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <FileIcon name={doc.name} />
                      <span className="text-gray-900">{doc.name}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                      {subjectName(doc.subject_id)}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-gray-600">{doc.chunk_count}</td>
                  <td className="px-4 py-3 text-gray-500">{doc.created_at}</td>
                  <td className="px-4 py-3 text-right">
                    {confirmDelete === doc.name ? (
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleDelete(doc.name)}
                          className="rounded-lg bg-red-600 px-3 py-1 text-sm text-white hover:bg-red-700"
                        >
                          确认删除
                        </button>
                        <button
                          onClick={() => setConfirmDelete(null)}
                          className="rounded-lg px-3 py-1 text-sm text-gray-500 hover:bg-gray-100"
                        >
                          取消
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmDelete(doc.name)}
                        className="rounded-lg px-3 py-1 text-sm text-red-500 hover:bg-red-50"
                      >
                        删除
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/** 文件类型图标 */
function FileIcon({ name }: { name: string }) {
  const ext = name.split(".").pop()?.toLowerCase();
  const colors: Record<string, string> = {
    pdf: "bg-red-50 text-red-600",
    docx: "bg-blue-50 text-blue-600",
    txt: "bg-gray-100 text-gray-600",
  };
  const color = colors[ext || ""] || "bg-gray-100 text-gray-600";

  return (
    <span className={`flex h-7 w-7 items-center justify-center rounded text-xs font-medium ${color}`}>
      {(ext || "?").toUpperCase()}
    </span>
  );
}
