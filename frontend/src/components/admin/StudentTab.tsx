"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { apiGet, apiPost, apiPut, apiDelete, apiUpload } from "@/lib/api";
import type { UserInfo, PaginatedStudents, StudentCreate, AppSettings, Entitlements, AdminStudentProfile } from "@/types";

export function StudentTab() {
  const [students, setStudents] = useState<UserInfo[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [size] = useState(20);
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // 弹窗状态
  const [showCreate, setShowCreate] = useState(false);
  const [editingStudent, setEditingStudent] = useState<UserInfo | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);
  const [showSettings, setShowSettings] = useState(false);

  // 权益行内编辑状态（entLimit 空串=跟随全局；entMemory: "null"/"1"/"0"）
  const [entEditingId, setEntEditingId] = useState<number | null>(null);
  const [entLimit, setEntLimit] = useState("");
  const [entMemory, setEntMemory] = useState("null");
  const [entSaving, setEntSaving] = useState(false);

  // 查看画像
  const [profileStudent, setProfileStudent] = useState<UserInfo | null>(null);

  // 批量导入
  const [batchResult, setBatchResult] = useState<{
    success: number;
    failed: number;
    errors: { row: number; student_id: string; reason: string }[];
  } | null>(null);
  const [uploading, setUploading] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const loadStudents = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ page: String(page), size: String(size) });
      if (keyword) params.set("keyword", keyword);
      const data = await apiGet<PaginatedStudents>(
        `/api/admin/students?${params.toString()}`
      );
      setStudents(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [page, size, keyword]);

  useEffect(() => {
    loadStudents();
  }, [loadStudents]);

  function handleSearch() {
    setPage(1);
    loadStudents();
  }

  async function handleCreate(data: StudentCreate) {
    try {
      await apiPost("/api/admin/students", data);
      setShowCreate(false);
      loadStudents();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    }
  }

  async function handleUpdate(id: number, data: { name?: string; password?: string }) {
    try {
      await apiPut(`/api/admin/students/${id}`, data);
      setEditingStudent(null);
      loadStudents();
    } catch (err) {
      setError(err instanceof Error ? err.message : "修改失败");
    }
  }

  async function handleDelete(id: number) {
    try {
      await apiDelete(`/api/admin/students/${id}`);
      setConfirmDeleteId(null);
      loadStudents();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  }

  /** 开始行内编辑权益（配额/记忆开关） */
  function startEntEdit(s: UserInfo) {
    setEntEditingId(s.id);
    setEntLimit(s.daily_question_limit != null ? String(s.daily_question_limit) : "");
    setEntMemory(s.memory_enabled == null ? "null" : s.memory_enabled ? "1" : "0");
  }

  /** 保存权益（置空=跟随全局） */
  async function handleEntSave(id: number) {
    const data: Entitlements = {
      daily_question_limit: entLimit.trim() === "" ? null : Number(entLimit),
      memory_enabled: entMemory === "null" ? null : entMemory === "1",
    };
    setEntSaving(true);
    try {
      await apiPut(`/api/admin/students/${id}/entitlements`, data);
      setEntEditingId(null);
      loadStudents();
    } catch (err) {
      setError(err instanceof Error ? err.message : "权益保存失败");
    } finally {
      setEntSaving(false);
    }
  }

  async function handleBatchImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError("");
    try {
      const formData = new FormData();
      formData.append("file", file);
      const result = await apiUpload<{
        success: number;
        failed: number;
        errors: { row: number; student_id: string; reason: string }[];
      }>("/api/admin/students/batch", formData);
      setBatchResult(result);
      loadStudents();
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入失败");
    } finally {
      setUploading(false);
      if (fileInputRef.current) fileInputRef.current.value = "";
    }
  }

  const totalPages = Math.ceil(total / size);

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
        <div className="flex items-center gap-2">
          <input
            type="text"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            placeholder="搜索学号或姓名..."
            className="w-64 rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
          />
          <button
            onClick={handleSearch}
            className="rounded-lg bg-gray-100 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-200"
          >
            搜索
          </button>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowSettings(true)}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50"
          >
            全局设置
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept=".xlsx,.xls"
            onChange={handleBatchImport}
            className="hidden"
          />
          <button
            onClick={() => fileInputRef.current?.click()}
            disabled={uploading}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 transition-colors hover:bg-gray-50 disabled:opacity-50"
          >
            {uploading ? "导入中..." : "批量导入"}
          </button>
          <button
            onClick={() => setShowCreate(true)}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            + 新增学生
          </button>
        </div>
      </div>

      {/* 批量导入结果 */}
      {batchResult && (
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <div className="flex items-center justify-between">
            <p className="text-sm">
              <span className="font-medium text-green-600">成功导入 {batchResult.success} 人</span>
              {batchResult.failed > 0 && (
                <span className="ml-4 font-medium text-red-600">失败 {batchResult.failed} 人</span>
              )}
            </p>
            <button onClick={() => setBatchResult(null)} className="text-gray-400 hover:text-gray-600">✕</button>
          </div>
          {batchResult.errors.length > 0 && (
            <div className="mt-3 space-y-1">
              {batchResult.errors.map((err, i) => (
                <div key={i} className="text-sm text-red-500">
                  第 {err.row} 行：{err.student_id || "(空)"} - {err.reason}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 学生表格 */}
      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50 text-left text-gray-500">
              <th className="px-4 py-3 font-medium">学号</th>
              <th className="px-4 py-3 font-medium">姓名</th>
              <th className="px-4 py-3 font-medium">每日配额</th>
              <th className="px-4 py-3 font-medium">记忆开关</th>
              <th className="px-4 py-3 font-medium">创建时间</th>
              <th className="px-4 py-3 font-medium text-right">操作</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-400">加载中...</td>
              </tr>
            ) : students.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-gray-400">暂无学生数据</td>
              </tr>
            ) : (
              students.map((s) => (
                <tr key={s.id} className="border-b border-gray-100 last:border-0 hover:bg-gray-50">
                  <td className="px-4 py-3 text-gray-900">{s.student_id}</td>
                  <td className="px-4 py-3 text-gray-900">{s.name}</td>
                  {entEditingId === s.id ? (
                    <>
                      <td className="px-4 py-3">
                        <input
                          type="number"
                          min={0}
                          value={entLimit}
                          onChange={(e) => setEntLimit(e.target.value)}
                          placeholder="空=跟随全局"
                          className="w-24 rounded-lg border border-gray-300 px-2 py-1 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                        />
                      </td>
                      <td className="px-4 py-3">
                        <select
                          value={entMemory}
                          onChange={(e) => setEntMemory(e.target.value)}
                          className="rounded-lg border border-gray-300 px-2 py-1 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                        >
                          <option value="null">跟随全局</option>
                          <option value="1">开</option>
                          <option value="0">关</option>
                        </select>
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="px-4 py-3 text-gray-500">
                        {s.daily_question_limit != null ? s.daily_question_limit : (
                          <span className="text-gray-400">跟随全局</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-500">
                        {s.memory_enabled == null ? (
                          <span className="text-gray-400">跟随全局</span>
                        ) : s.memory_enabled ? (
                          <span className="text-green-600">开</span>
                        ) : (
                          <span className="text-gray-500">关</span>
                        )}
                      </td>
                    </>
                  )}
                  <td className="px-4 py-3 text-gray-500">{s.created_at}</td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex items-center justify-end gap-2">
                      {entEditingId === s.id ? (
                        <>
                          <button
                            onClick={() => handleEntSave(s.id)}
                            disabled={entSaving}
                            className="rounded-lg bg-blue-600 px-3 py-1 text-sm text-white hover:bg-blue-700 disabled:opacity-50"
                          >
                            {entSaving ? "保存中..." : "保存权益"}
                          </button>
                          <button
                            onClick={() => setEntEditingId(null)}
                            className="rounded-lg px-3 py-1 text-sm text-gray-500 hover:bg-gray-100"
                          >
                            取消
                          </button>
                        </>
                      ) : (
                        <button
                          onClick={() => startEntEdit(s)}
                          className="rounded-lg px-3 py-1 text-sm text-gray-600 hover:bg-gray-100"
                        >
                          权益
                        </button>
                      )}
                      <button
                        onClick={() => setProfileStudent(s)}
                        className="rounded-lg px-3 py-1 text-sm text-gray-600 hover:bg-gray-100"
                      >
                        画像
                      </button>
                      <button
                        onClick={() => setEditingStudent(s)}
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

      {/* 分页 */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className="text-sm text-gray-500">共 {total} 条</p>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="rounded-lg border border-gray-300 px-3 py-1 text-sm disabled:opacity-50"
            >
              上一页
            </button>
            <span className="text-sm text-gray-600">
              {page} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="rounded-lg border border-gray-300 px-3 py-1 text-sm disabled:opacity-50"
            >
              下一页
            </button>
          </div>
        </div>
      )}

      {/* 新增学生弹窗 */}
      {showCreate && (
        <CreateStudentModal
          onClose={() => setShowCreate(false)}
          onCreate={handleCreate}
        />
      )}

      {/* 编辑学生弹窗 */}
      {editingStudent && (
        <EditStudentModal
          student={editingStudent}
          onClose={() => setEditingStudent(null)}
          onSave={handleUpdate}
        />
      )}

      {/* 全局设置弹窗 */}
      {showSettings && (
        <GlobalSettingsModal onClose={() => setShowSettings(false)} />
      )}

      {/* 学生画像弹窗 */}
      {profileStudent && (
        <AdminProfileModal
          student={profileStudent}
          onClose={() => setProfileStudent(null)}
        />
      )}
    </div>
  );
}

/** 新增学生弹窗 */
function CreateStudentModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (data: StudentCreate) => void;
}) {
  const [studentId, setStudentId] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onCreate({ student_id: studentId, name, password });
  }

  return (
    <Modal title="新增学生" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="学号" required>
          <input
            type="text"
            value={studentId}
            onChange={(e) => setStudentId(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            required
          />
        </Field>
        <Field label="姓名" required>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            required
          />
        </Field>
        <Field label="初始密码" required>
          <input
            type="text"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            required
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
            创建
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** 编辑学生弹窗 */
function EditStudentModal({
  student,
  onClose,
  onSave,
}: {
  student: UserInfo;
  onClose: () => void;
  onSave: (id: number, data: { name?: string; password?: string }) => void;
}) {
  const [name, setName] = useState(student.name);
  const [password, setPassword] = useState("");
  const [resetPassword, setResetPassword] = useState(false);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const data: { name?: string; password?: string } = {};
    if (name !== student.name) data.name = name;
    if (resetPassword && password) data.password = password;
    onSave(student.id, data);
  }

  return (
    <Modal title="编辑学生" onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="学号">
          <input
            type="text"
            value={student.student_id}
            disabled
            className="w-full rounded-lg border border-gray-200 bg-gray-50 px-4 py-2 text-sm text-gray-500"
          />
        </Field>
        <Field label="姓名">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
          />
        </Field>
        <div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={resetPassword}
              onChange={(e) => setResetPassword(e.target.checked)}
              className="rounded border-gray-300"
            />
            重置密码
          </label>
        </div>
        {resetPassword && (
          <Field label="新密码" required>
            <input
              type="text"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              required
            />
          </Field>
        )}
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

/** 管理端学生画像弹窗（GET /api/admin/students/{id}/profile） */
function AdminProfileModal({
  student,
  onClose,
}: {
  student: UserInfo;
  onClose: () => void;
}) {
  const [profile, setProfile] = useState<AdminStudentProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    apiGet<AdminStudentProfile>(`/api/admin/students/${student.id}/profile`)
      .then(setProfile)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setLoading(false));
  }, [student.id]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={onClose}
    >
      <div
        className="max-h-[80vh] w-full max-w-lg overflow-y-auto rounded-xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-900">
            {student.name}（{student.student_id}）的学习画像
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>
        {loading ? (
          <p className="py-8 text-center text-sm text-gray-400">加载中...</p>
        ) : error ? (
          <div className="rounded-lg bg-red-50 px-4 py-2.5 text-sm text-red-600">{error}</div>
        ) : profile ? (
          <div className="space-y-4">
            {/* 学习风格 */}
            <div>
              <h4 className="mb-1 text-sm font-medium text-gray-700">学习风格</h4>
              {profile.style_profile ? (
                <p className="rounded-lg bg-gray-50 px-4 py-3 text-sm text-gray-600">{profile.style_profile}</p>
              ) : (
                <p className="text-sm text-gray-400">暂无画像数据</p>
              )}
            </div>

            {/* 薄弱知识点 */}
            <div>
              <h4 className="mb-1 text-sm font-medium text-gray-700">薄弱知识点</h4>
              {profile.weak_kps.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {profile.weak_kps.map((kp) => (
                    <span
                      key={kp.kp_id}
                      className="inline-flex items-center gap-1 rounded-lg bg-red-50 px-3 py-1 text-xs text-red-600"
                    >
                      {kp.kp_id}
                      <span className="text-red-400">掌握{Math.round(kp.rate * 100)}%</span>
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-400">暂无薄弱知识点</p>
              )}
            </div>

            {/* 最近考试 */}
            {profile.recent_exam && (
              <div>
                <h4 className="mb-1 text-sm font-medium text-gray-700">最近考试</h4>
                <p className="text-sm text-gray-600">
                  {profile.recent_exam.date} {profile.recent_exam.subject}：
                  {profile.recent_exam.score}/{profile.recent_exam.total}分
                </p>
              </div>
            )}

            {/* 错题统计 */}
            <div>
              <h4 className="mb-1 text-sm font-medium text-gray-700">错题统计</h4>
              <div className="flex gap-4">
                <span className="text-sm text-gray-600">
                  总错题 <span className="font-semibold text-gray-900">{profile.wrong_stats.total}</span> 题
                </span>
                <span className="text-sm text-gray-600">
                  未掌握 <span className="font-semibold text-red-500">{profile.wrong_stats.unmastered}</span> 题
                </span>
              </div>
              {profile.wrong_stats.hot_wrong_kps.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2">
                  {profile.wrong_stats.hot_wrong_kps.map((kp) => (
                    <span
                      key={kp.kp_id}
                      className="rounded bg-amber-50 px-2 py-0.5 text-xs text-amber-600"
                    >
                      {kp.kp_id}（错 {kp.wrong_count} 次）
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </div>
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

/** 全局设置弹窗（GET/PUT /api/admin/settings，app_settings 各键） */
function GlobalSettingsModal({ onClose }: { onClose: () => void }) {
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiGet<AppSettings>("/api/admin/settings")
      .then(setSettings)
      .catch((err) => setError(err instanceof Error ? err.message : "加载失败"))
      .finally(() => setLoading(false));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!settings) return;
    setSaving(true);
    setError("");
    try {
      await apiPut("/api/admin/settings", settings);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  function setNum(key: keyof AppSettings, value: string) {
    setSettings((prev) => (prev ? { ...prev, [key]: Number(value) } : prev));
  }

  const numberFields: { key: keyof AppSettings; label: string }[] = [
    { key: "daily_question_limit_default", label: "每人每日提问上限（全局默认）" },
    { key: "chat_concurrency", label: "同时对话上限" },
    { key: "chat_queue_size", label: "排队队列长度上限" },
    { key: "profile_update_interval", label: "画像总结触发轮数" },
  ];

  return (
    <Modal title="全局设置" onClose={onClose}>
      {loading ? (
        <p className="py-8 text-center text-sm text-gray-400">加载中...</p>
      ) : !settings ? (
        <div className="rounded-lg bg-red-50 px-4 py-2.5 text-sm text-red-600">{error || "加载失败"}</div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
          {numberFields.map((f) => (
            <Field key={f.key} label={f.label}>
              <input
                type="number"
                min={0}
                value={settings[f.key] as number}
                onChange={(e) => setNum(f.key, e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                required
              />
            </Field>
          ))}
          <div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={settings.memory_enabled_default}
                onChange={(e) =>
                  setSettings((prev) =>
                    prev ? { ...prev, memory_enabled_default: e.target.checked } : prev
                  )
                }
                className="rounded border-gray-300"
              />
              学生记忆功能总开关
            </label>
          </div>
          {error && (
            <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">{error}</div>
          )}
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
              disabled={saving}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {saving ? "保存中..." : "保存"}
            </button>
          </div>
        </form>
      )}
    </Modal>
  );
}
