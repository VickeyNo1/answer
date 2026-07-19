"use client";

import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "@/lib/api";
import type { Subject, SubjectCreate, SubjectUpdate } from "@/types";

const CATEGORY_GROUPS: { key: string; label: string }[] = [
  { key: "general", label: "财务通用类" },
  { key: "professional", label: "专业课程类" },
];

export function SubjectTab() {
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<Subject | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const loadSubjects = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiGet<Subject[]>("/api/subjects");
      setSubjects(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSubjects();
  }, [loadSubjects]);

  async function handleCreate(data: SubjectCreate) {
    try {
      await apiPost("/api/admin/subjects", data);
      setShowCreate(false);
      loadSubjects();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    }
  }

  async function handleUpdate(id: number, data: SubjectUpdate) {
    try {
      await apiPut(`/api/admin/subjects/${id}`, data);
      setEditing(null);
      loadSubjects();
    } catch (err) {
      setError(err instanceof Error ? err.message : "修改失败");
    }
  }

  async function handleDelete(id: number) {
    try {
      await apiDelete(`/api/admin/subjects/${id}`);
      setConfirmDeleteId(null);
      loadSubjects();
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

      {/* 操作栏 */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">按「财务通用类 / 专业课程类」管理科目，学生对话时可选择科目以获得更精准的知识检索。</p>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
        >
          + 新增科目
        </button>
      </div>

      {loading ? (
        <div className="rounded-xl border border-gray-200 bg-white px-4 py-8 text-center text-gray-400">加载中...</div>
      ) : (
        CATEGORY_GROUPS.map((group) => {
          const items = subjects.filter((s) => s.category === group.key);
          return (
            <div key={group.key} className="space-y-2">
              <h3 className="text-sm font-semibold text-gray-900">{group.label}</h3>
              <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-gray-200 bg-gray-50 text-left text-gray-500">
                      <th className="px-4 py-3 font-medium">科目名称</th>
                      <th className="px-4 py-3 font-medium">描述</th>
                      <th className="px-4 py-3 font-medium text-center">排序</th>
                      <th className="px-4 py-3 font-medium text-right">操作</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.length === 0 ? (
                      <tr>
                        <td colSpan={4} className="px-4 py-6 text-center text-gray-400">暂无科目</td>
                      </tr>
                    ) : (
                      items.map((s) => (
                        <tr key={s.id} className="border-b border-gray-100 last:border-0 hover:bg-gray-50">
                          <td className="px-4 py-3 text-gray-900">{s.name}</td>
                          <td className="px-4 py-3 text-gray-500">{s.description || "-"}</td>
                          <td className="px-4 py-3 text-center text-gray-500">{s.sort_order}</td>
                          <td className="px-4 py-3 text-right">
                            <div className="flex items-center justify-end gap-2">
                              <button
                                onClick={() => setEditing(s)}
                                className="rounded-lg px-3 py-1 text-sm text-blue-600 hover:bg-blue-50"
                              >
                                编辑
                              </button>
                              {confirmDeleteId === s.id ? (
                                <>
                                  <button
                                    onClick={() => handleDelete(s.id)}
                                    className="rounded-lg bg-red-600 px-3 py-1 text-sm text-white hover:bg-red-700"
                                  >
                                    确认删除
                                  </button>
                                  <button
                                    onClick={() => setConfirmDeleteId(null)}
                                    className="rounded-lg px-3 py-1 text-sm text-gray-500 hover:bg-gray-100"
                                  >
                                    取消
                                  </button>
                                </>
                              ) : (
                                <button
                                  onClick={() => setConfirmDeleteId(s.id)}
                                  className="rounded-lg px-3 py-1 text-sm text-red-500 hover:bg-red-50"
                                >
                                  删除
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })
      )}

      {/* 新增/编辑弹窗 */}
      {showCreate && (
        <SubjectModal
          title="新增科目"
          onClose={() => setShowCreate(false)}
          onSubmit={(data) => handleCreate(data as SubjectCreate)}
        />
      )}
      {editing && (
        <SubjectModal
          title="编辑科目"
          subject={editing}
          onClose={() => setEditing(null)}
          onSubmit={(data) => handleUpdate(editing.id, data)}
        />
      )}
    </div>
  );
}

/** 科目新增/编辑弹窗 */
function SubjectModal({
  title,
  subject,
  onClose,
  onSubmit,
}: {
  title: string;
  subject?: Subject;
  onClose: () => void;
  onSubmit: (data: SubjectCreate | SubjectUpdate) => void;
}) {
  const [name, setName] = useState(subject?.name || "");
  const [category, setCategory] = useState(subject?.category || "general");
  const [description, setDescription] = useState(subject?.description || "");
  const [sortOrder, setSortOrder] = useState(String(subject?.sort_order ?? 0));

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onSubmit({
      name,
      category,
      description,
      sort_order: parseInt(sortOrder, 10) || 0,
    });
  }

  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="科目名称" required>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="如 初级会计学"
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            required
          />
        </Field>
        <Field label="分类" required>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
          >
            <option value="general">财务通用类</option>
            <option value="professional">专业课程类</option>
          </select>
        </Field>
        <Field label="描述">
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            rows={3}
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
          />
        </Field>
        <Field label="排序（数字越小越靠前）">
          <input
            type="number"
            value={sortOrder}
            onChange={(e) => setSortOrder(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
          />
        </Field>
        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
          >
            取消
          </button>
          <button
            type="submit"
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            保存
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** 通用弹窗组件 */
function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        {children}
      </div>
    </div>
  );
}

/** 表单字段 */
function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-gray-700">
        {label}
        {required && <span className="text-red-500"> *</span>}
      </label>
      {children}
    </div>
  );
}
