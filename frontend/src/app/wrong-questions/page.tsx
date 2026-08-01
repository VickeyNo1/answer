"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { apiGet, apiPost } from "@/lib/api";
import { getToken } from "@/lib/auth";
import type {
  Subject,
  PaginatedWrongQuestions,
  WrongQuestionListItem,
  WrongQuestionRetryResponse,
} from "@/types";

export default function WrongQuestionsPage() {
  const router = useRouter();
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [data, setData] = useState<PaginatedWrongQuestions>({ total: 0, items: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // 筛选
  const [subject, setSubject] = useState("");
  const [mastered, setMastered] = useState<string>(""); // "" / "0" / "1"

  // 分页
  const [page, setPage] = useState(1);
  const [pageSize] = useState(10);

  // 重练弹窗
  const [retryItem, setRetryItem] = useState<WrongQuestionListItem | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    apiGet<Subject[]>("/api/subjects")
      .then(setSubjects)
      .catch(() => {});
  }, [router]);

  const loadWrongQuestions = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({
        page: String(page),
        page_size: String(pageSize),
      });
      if (subject) params.set("subject", subject);
      if (mastered) params.set("mastered", mastered);
      const d = await apiGet<PaginatedWrongQuestions>(
        `/api/wrong-questions?${params.toString()}`
      );
      setData(d);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, subject, mastered]);

  useEffect(() => {
    loadWrongQuestions();
  }, [loadWrongQuestions]);

  function handleFilter() {
    setPage(1);
    loadWrongQuestions();
  }

  function handleAskAi(kpId: string, subj: string) {
    router.push(
      `/?ask=${encodeURIComponent("请讲解知识点 " + kpId)}&subject=${subj || ""}`
    );
  }

  const totalPages = Math.ceil(data.total / pageSize);

  return (
    <div className="flex min-h-screen flex-col bg-gray-50">
      {/* 顶栏 */}
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3 md:px-6">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push("/")}
            className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100"
            title="返回"
          >
            <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <h1 className="text-lg font-semibold text-gray-900">错题本</h1>
          <span className="text-sm text-gray-400">共 {data.total} 题</span>
        </div>
        <a href="/" className="rounded-lg px-3 py-1 text-sm text-blue-600 hover:bg-blue-50">
          返回对话
        </a>
      </header>

      {error && (
        <div className="flex items-center justify-between bg-red-50 px-4 py-2 text-sm text-red-600 md:px-6">
          <span>{error}</span>
          <button onClick={() => setError("")} className="text-red-400 hover:text-red-600">✕</button>
        </div>
      )}

      {/* 筛选栏 */}
      <div className="flex flex-wrap items-center gap-2 border-b border-gray-200 bg-white px-4 py-3 md:px-6">
        <select
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
        >
          <option value="">全部科目</option>
          {subjects.map((s) => (
            <option key={s.subject} value={s.subject}>{s.name}</option>
          ))}
        </select>
        <select
          value={mastered}
          onChange={(e) => setMastered(e.target.value)}
          className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
        >
          <option value="">全部状态</option>
          <option value="0">未掌握</option>
          <option value="1">已掌握</option>
        </select>
        <button
          onClick={handleFilter}
          className="rounded-lg bg-gray-100 px-4 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-200"
        >
          筛选
        </button>
      </div>

      {/* 错题列表 */}
      <main className="mx-auto w-full max-w-3xl flex-1 overflow-y-auto p-4 md:p-6">
        {loading ? (
          <p className="py-8 text-center text-sm text-gray-400">加载中...</p>
        ) : data.items.length === 0 ? (
          <div className="py-12 text-center">
            <p className="text-sm text-gray-400">
              {error ? error : "暂无错题记录"}
            </p>
            <p className="mt-1 text-xs text-gray-300">
              交卷判分后，错题会自动加入错题本
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {data.items.map((item) => (
              <div
                key={item.id}
                className={`rounded-xl border bg-white p-4 ${
                  item.mastered ? "border-green-200" : "border-gray-200"
                }`}
              >
                {/* 题目头部 */}
                <div className="mb-2 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {item.question_type && (
                      <span className="rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                        {item.question_type}
                      </span>
                    )}
                    <span className="text-xs text-gray-400">
                      错 {item.wrong_count} 次
                    </span>
                    {item.mastered ? (
                      <span className="rounded bg-green-50 px-2 py-0.5 text-xs text-green-600">
                        ✓ 已掌握
                      </span>
                    ) : (
                      <span className="rounded bg-red-50 px-2 py-0.5 text-xs text-red-500">
                        未掌握
                      </span>
                    )}
                  </div>
                  <span className="text-xs text-gray-400">
                    {item.last_wrong_at.slice(0, 10)}
                  </span>
                </div>

                {/* 题目内容 */}
                {item.materials && (
                  <pre className="mb-2 whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-sm text-gray-700">
                    {item.materials}
                  </pre>
                )}
                {item.stem && (
                  <p className="mb-2 text-sm text-gray-900">{item.stem}</p>
                )}
                {item.sub_questions && item.sub_questions.length > 0 && (
                  <ol className="mb-2 list-inside list-decimal space-y-1 text-sm text-gray-700">
                    {item.sub_questions.map((sq, i) => (
                      <li key={i} className="whitespace-pre-wrap">
                        {typeof sq === "string" ? sq : sq.question || JSON.stringify(sq)}
                      </li>
                    ))}
                  </ol>
                )}
                {item.options && (
                  <div className="mb-2 space-y-1">
                    {Object.entries(item.options).map(([key, val]) => (
                      <p key={key} className="text-sm text-gray-600">
                        {key}. {val}
                      </p>
                    ))}
                  </div>
                )}

                {/* 知识点标签 */}
                {item.knowledge_point_ids.length > 0 && (
                  <div className="mb-2 flex flex-wrap gap-1.5">
                    {item.knowledge_point_ids.map((kp) => (
                      <button
                        key={kp}
                        onClick={() => handleAskAi(kp, item.subject)}
                        className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-0.5 text-xs text-blue-600 hover:bg-blue-100"
                      >
                        {kp} · 问 AI
                      </button>
                    ))}
                  </div>
                )}

                {/* 重练按钮 */}
                {!item.mastered && (
                  <button
                    onClick={() => setRetryItem(item)}
                    className="rounded-lg border border-blue-300 bg-blue-50 px-4 py-1.5 text-sm font-medium text-blue-600 hover:bg-blue-100"
                  >
                    重练此题
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </main>

      {/* 分页 */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between border-t border-gray-200 bg-white px-4 py-3 md:px-6">
          <span className="text-sm text-gray-500">
            第 {page} / {totalPages} 页
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="rounded-lg border border-gray-300 px-3 py-1 text-sm disabled:opacity-50"
            >
              上一页
            </button>
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

      {/* 重练弹窗 */}
      {retryItem && (
        <RetryModal
          item={retryItem}
          onClose={() => setRetryItem(null)}
          onResult={(correct) => {
            if (correct) {
              // 答对后刷新列表（该题变为已掌握）
              loadWrongQuestions();
            }
          }}
        />
      )}
    </div>
  );
}

/** 重练弹窗 */
function RetryModal({
  item,
  onClose,
  onResult,
}: {
  item: WrongQuestionListItem;
  onClose: () => void;
  onResult: (correct: boolean) => void;
}) {
  const [answer, setAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<WrongQuestionRetryResponse | null>(null);
  const [error, setError] = useState("");

  async function handleSubmit() {
    if (!answer.trim()) {
      setError("请输入你的答案");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const resp = await apiPost<WrongQuestionRetryResponse>(
        `/api/wrong-questions/${item.id}/retry`,
        { answer }
      );
      setResult(resp);
      onResult(resp.correct);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setSubmitting(false);
    }
  }

  const isObjective =
    item.question_type === "单选" || item.question_type === "多选";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      onClick={onClose}
    >
      <div
        className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-xl bg-white p-6 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-gray-900">重练错题</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">✕</button>
        </div>

        {/* 题目展示 */}
        <div className="mb-4">
          {item.question_type && (
            <span className="mb-2 inline-block rounded bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
              {item.question_type}
            </span>
          )}
          {item.materials && (
            <pre className="mb-2 whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-sm text-gray-700">
              {item.materials}
            </pre>
          )}
          {item.stem && <p className="mb-2 text-sm text-gray-900">{item.stem}</p>}
          {item.sub_questions && item.sub_questions.length > 0 && (
            <ol className="mb-2 list-inside list-decimal space-y-1 text-sm text-gray-700">
              {item.sub_questions.map((sq, i) => (
                <li key={i} className="whitespace-pre-wrap">
                  {typeof sq === "string" ? sq : sq.question || JSON.stringify(sq)}
                </li>
              ))}
            </ol>
          )}
          {item.options && !result && (
            <div className="space-y-2">
              {Object.entries(item.options).map(([key, val]) => (
                <label
                  key={key}
                  className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors ${
                    answer === key
                      ? "border-blue-500 bg-blue-50 text-blue-700"
                      : "border-gray-200 hover:bg-gray-50"
                  }`}
                >
                  <input
                    type="radio"
                    name="retry-answer"
                    checked={answer === key}
                    onChange={() => setAnswer(key)}
                    className="h-4 w-4 text-blue-600"
                  />
                  <span className="font-medium">{key}.</span>
                  <span className="text-gray-700">{val}</span>
                </label>
              ))}
            </div>
          )}
        </div>

        {/* 答题区（主观题用 textarea，客观题用 radio；结果出来后隐藏） */}
        {!result && !isObjective && (
          <textarea
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="在此输入你的解答…"
            rows={6}
            className="mb-4 w-full resize-y rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
          />
        )}

        {/* 错误提示 */}
        {error && (
          <div className="mb-3 rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
            {error}
          </div>
        )}

        {/* 判分结果 */}
        {result && (
          <div className="space-y-3">
            <div
              className={`rounded-lg px-4 py-3 ${
                result.correct ? "bg-green-50" : "bg-red-50"
              }`}
            >
              <p
                className={`text-sm font-medium ${
                  result.correct ? "text-green-700" : "text-red-600"
                }`}
              >
                {result.correct ? "✓ 答对了！已标记为掌握" : "✗ 答案不正确"}
              </p>
              <p className="mt-1 text-sm text-gray-600">
                <span className="text-gray-400">你的答案：</span>
                {answer}
              </p>
              {result.correct_answer && (
                <p className="text-sm text-green-700">
                  <span className="text-gray-400">参考答案：</span>
                  {result.correct_answer}
                </p>
              )}
            </div>
            {result.explanation && (
              <div className="rounded-lg bg-gray-50 px-4 py-3">
                <p className="text-sm text-gray-600">
                  <span className="text-gray-400">解析：</span>
                  {result.explanation}
                </p>
              </div>
            )}
            <button
              onClick={onClose}
              className="w-full rounded-lg border border-gray-300 py-2 text-sm text-gray-600 hover:bg-gray-50"
            >
              关闭
            </button>
          </div>
        )}

        {/* 提交按钮 */}
        {!result && (
          <div className="flex justify-end gap-2">
            <button
              onClick={onClose}
              className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50"
            >
              取消
            </button>
            <button
              onClick={handleSubmit}
              disabled={submitting}
              className="rounded-lg bg-blue-600 px-6 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {submitting ? "判分中..." : "提交判分"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
