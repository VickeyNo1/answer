"use client";

import { useState, useEffect, useCallback, Fragment } from "react";
import { apiGet, apiPut } from "@/lib/api";
import type {
  AdminExamListOut,
  ExamDetailResponse,
  AdminScoreUpdateResponse,
} from "@/types";

const PAGE_SIZE = 20;

export function ExamTab() {
  const [items, setItems] = useState<AdminExamListOut["items"]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [filterStudent, setFilterStudent] = useState("");
  const [filterSubject, setFilterSubject] = useState("");
  const [filterDateFrom, setFilterDateFrom] = useState("");
  const [filterDateTo, setFilterDateTo] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  // 展开详情
  const [detailExamId, setDetailExamId] = useState<number | null>(null);
  const [detail, setDetail] = useState<ExamDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  // 改分
  const [scoreEditing, setScoreEditing] = useState<string | null>(null); // `${examId}-${seq}`
  const [scoreInput, setScoreInput] = useState("");
  const [scoreReason, setScoreReason] = useState("");

  const loadList = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(PAGE_SIZE),
      });
      if (filterStudent) params.set("student_id", filterStudent);
      if (filterSubject) params.set("subject", filterSubject);
      if (filterDateFrom) params.set("date_from", filterDateFrom);
      if (filterDateTo) params.set("date_to", filterDateTo);
      const data = await apiGet<AdminExamListOut>(
        `/api/admin/exams?${params.toString()}`
      );
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [page, filterStudent, filterSubject, filterDateFrom, filterDateTo]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  const loadDetail = useCallback(async (examId: number) => {
    setDetailLoading(true);
    try {
      const d = await apiGet<ExamDetailResponse>(`/api/admin/exams/${examId}`);
      setDetail(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载详情失败");
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const handleRowClick = useCallback((examId: number) => {
    if (detailExamId === examId) {
      setDetailExamId(null);
      setDetail(null);
      return;
    }
    setDetailExamId(examId);
    setDetail(null);
    loadDetail(examId);
  }, [detailExamId, loadDetail]);

  const handleSaveScore = useCallback(async (examId: number, seq: number, fullScore: number) => {
    const score = Number(scoreInput);
    if (isNaN(score) || score < 0 || score > fullScore) {
      alert(`分数需在 0-${fullScore} 之间`);
      return;
    }
    try {
      await apiPut<AdminScoreUpdateResponse>(
        `/api/admin/exams/${examId}/answers/${seq}/score`,
        { score, reason: scoreReason || null }
      );
      // 刷新详情
      await loadDetail(examId);
      setScoreEditing(null);
      setScoreInput("");
      setScoreReason("");
      // 刷新列表（总分变了）
      loadList();
    } catch (err) {
      alert(err instanceof Error ? err.message : "改分失败");
    }
  }, [scoreInput, scoreReason, loadDetail, loadList]);

  const totalPages = Math.ceil(total / PAGE_SIZE) || 1;

  return (
    <div className="space-y-4">
      {error && (
        <div className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">{error}</div>
      )}

      {/* 筛选 */}
      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-gray-200 bg-white p-4">
        <div>
          <label className="mb-1 block text-xs text-gray-500">学号</label>
          <input
            value={filterStudent}
            onChange={(e) => setFilterStudent(e.target.value)}
            placeholder="学号筛选"
            className="w-32 rounded-lg border border-gray-300 px-2 py-1 text-sm outline-none focus:border-blue-500"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-gray-500">科目</label>
          <input
            value={filterSubject}
            onChange={(e) => setFilterSubject(e.target.value)}
            placeholder="科目枚举"
            className="w-32 rounded-lg border border-gray-300 px-2 py-1 text-sm outline-none focus:border-blue-500"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-gray-500">起始</label>
          <input
            type="date"
            value={filterDateFrom}
            onChange={(e) => setFilterDateFrom(e.target.value)}
            className="rounded-lg border border-gray-300 px-2 py-1 text-sm outline-none focus:border-blue-500"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs text-gray-500">结束</label>
          <input
            type="date"
            value={filterDateTo}
            onChange={(e) => setFilterDateTo(e.target.value)}
            className="rounded-lg border border-gray-300 px-2 py-1 text-sm outline-none focus:border-blue-500"
          />
        </div>
        <button
          onClick={() => { setPage(1); loadList(); }}
          className="rounded-lg bg-blue-600 px-4 py-1.5 text-sm text-white hover:bg-blue-700"
        >
          查询
        </button>
      </div>

      {/* 列表 */}
      <div className="overflow-x-auto rounded-lg border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead className="border-b border-gray-200 bg-gray-50 text-gray-500">
            <tr>
              <th className="px-3 py-2 text-left font-medium">ID</th>
              <th className="px-3 py-2 text-left font-medium">学号</th>
              <th className="px-3 py-2 text-left font-medium">姓名</th>
              <th className="px-3 py-2 text-left font-medium">科目</th>
              <th className="px-3 py-2 text-left font-medium">状态</th>
              <th className="px-3 py-2 text-right font-medium">题数</th>
              <th className="px-3 py-2 text-right font-medium">得分</th>
              <th className="px-3 py-2 text-left font-medium">交卷时间</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={8} className="px-3 py-8 text-center text-gray-400">加载中…</td></tr>
            ) : items.length === 0 ? (
              <tr><td colSpan={8} className="px-3 py-8 text-center text-gray-400">暂无数据</td></tr>
            ) : (
              items.map((item) => (
                <Fragment key={item.id}>
                  <tr
                    key={item.id}
                    onClick={() => handleRowClick(item.id)}
                    className={`cursor-pointer border-b border-gray-100 hover:bg-gray-50 ${
                      detailExamId === item.id ? "bg-blue-50" : ""
                    }`}
                  >
                    <td className="px-3 py-2 text-gray-500">{item.id}</td>
                    <td className="px-3 py-2 text-gray-700">{item.student_id}</td>
                    <td className="px-3 py-2 text-gray-700">{item.student_name}</td>
                    <td className="px-3 py-2 text-gray-500">{item.subject}</td>
                    <td className="px-3 py-2">
                      <StatusBadge status={item.status} />
                    </td>
                    <td className="px-3 py-2 text-right text-gray-500">{item.question_count}</td>
                    <td className="px-3 py-2 text-right text-gray-700">
                      {item.obtained_score ?? "—"} / {item.total_score}
                    </td>
                    <td className="px-3 py-2 text-gray-400">
                      {item.submitted_at
                        ? new Date(item.submitted_at).toLocaleString()
                        : "—"}
                    </td>
                  </tr>
                  {detailExamId === item.id && (
                    <tr key={`${item.id}-detail`} className="bg-gray-50">
                      <td colSpan={8} className="px-6 py-4">
                        {detailLoading ? (
                          <p className="text-gray-400">加载详情…</p>
                        ) : detail ? (
                          <div className="space-y-3">
                            {detail.answers.map((a) => {
                              const editKey = `${item.id}-${a.seq}`;
                              const isEditing = scoreEditing === editKey;
                              const needsReview =
                                a.disputed === 1 || a.score === null;
                              return (
                                <div
                                  key={a.seq}
                                  className={`rounded-lg border bg-white p-3 ${
                                    needsReview ? "border-amber-300" : "border-gray-200"
                                  }`}
                                >
                                  <div className="mb-1 flex items-center justify-between">
                                    <span className="text-sm text-gray-500">
                                      第 {a.seq} 题 · {a.question_type} · 满分 {a.full_score}
                                      {a.disputed === 1 && (
                                        <span className="ml-2 rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-600">异议</span>
                                      )}
                                      {a.score === null && (
                                        <span className="ml-2 rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-600">未判</span>
                                      )}
                                    </span>
                                    <span className="text-sm font-semibold text-gray-700">
                                      {a.score ?? "—"} / {a.full_score}
                                    </span>
                                  </div>
                                  <div className="mb-1 text-sm text-gray-600">
                                    <span className="text-gray-400">作答：</span>{a.my_answer || "（未作答）"}
                                  </div>
                                  {a.correct_answer && (
                                    <div className="mb-1 text-sm text-green-700">
                                      <span className="text-gray-400">参考答案：</span>{a.correct_answer}
                                    </div>
                                  )}
                                  {a.llm_reason && (
                                    <div className="mb-2 text-sm text-gray-500">
                                      <span className="text-gray-400">判分理由：</span>{a.llm_reason}
                                    </div>
                                  )}
                                  {isEditing ? (
                                    <div className="flex flex-wrap items-center gap-2">
                                      <input
                                        type="number"
                                        step="0.5"
                                        min={0}
                                        max={a.full_score}
                                        value={scoreInput}
                                        onChange={(e) => setScoreInput(e.target.value)}
                                        className="w-20 rounded border border-gray-300 px-2 py-1 text-sm"
                                        placeholder="分数"
                                      />
                                      <input
                                        value={scoreReason}
                                        onChange={(e) => setScoreReason(e.target.value)}
                                        className="flex-1 rounded border border-gray-300 px-2 py-1 text-sm"
                                        placeholder="改分理由（可选）"
                                      />
                                      <button
                                        onClick={() => handleSaveScore(item.id, a.seq, a.full_score)}
                                        className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700"
                                      >
                                        保存
                                      </button>
                                      <button
                                        onClick={() => { setScoreEditing(null); setScoreInput(""); setScoreReason(""); }}
                                        className="rounded border border-gray-300 px-3 py-1 text-xs text-gray-500 hover:bg-gray-50"
                                      >
                                        取消
                                      </button>
                                    </div>
                                  ) : (
                                    <button
                                      onClick={() => {
                                        setScoreEditing(editKey);
                                        setScoreInput(String(a.score ?? 0));
                                        setScoreReason(a.llm_reason ?? "");
                                      }}
                                      className="rounded border border-gray-300 px-3 py-1 text-xs text-gray-500 hover:bg-gray-50"
                                    >
                                      改分
                                    </button>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        ) : null}
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* 分页 */}
      <div className="flex items-center justify-between text-sm text-gray-500">
        <span>共 {total} 条</span>
        <div className="flex gap-2">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded border border-gray-300 px-3 py-1 disabled:opacity-50"
          >
            上一页
          </button>
          <span className="px-2 py-1">{page} / {totalPages}</span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="rounded border border-gray-300 px-3 py-1 disabled:opacity-50"
          >
            下一页
          </button>
        </div>
      </div>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    ongoing: "bg-blue-100 text-blue-600",
    grading: "bg-amber-100 text-amber-600",
    graded: "bg-green-100 text-green-600",
  };
  return (
    <span className={`rounded px-1.5 py-0.5 text-xs ${styles[status] || "bg-gray-100 text-gray-500"}`}>
      {status === "ongoing" ? "进行中" : status === "grading" ? "判卷中" : "已判卷"}
    </span>
  );
}
