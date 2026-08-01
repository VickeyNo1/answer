"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import { apiGet, apiPost, apiPut } from "@/lib/api";
import { getToken } from "@/lib/auth";
import type {
  Subject,
  ExamCreateResponse,
  ExamDetailResponse,
  ExamSubmitResponse,
} from "@/types";

const QUESTION_TYPES = [
  { key: "单选", label: "单选题", max: 50 },
  { key: "多选", label: "多选题", max: 50 },
  { key: "计算", label: "计算题", max: 50 },
  { key: "综合", label: "综合题", max: 50 },
];

type Step = "setup" | "answer" | "result";

export default function ExamPage() {
  const router = useRouter();
  const [subjects, setSubjects] = useState<Subject[]>([]);
  const [selectedSubject, setSelectedSubject] = useState("");
  const [step, setStep] = useState<Step>("setup");
  const [counts, setCounts] = useState<Record<string, number>>({
    单选: 5, 多选: 3, 计算: 1, 综合: 0,
  });
  const [exam, setExam] = useState<ExamCreateResponse | null>(null);
  const [answers, setAnswers] = useState<Record<number, string>>({});
  const [detail, setDetail] = useState<ExamDetailResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!getToken()) { router.replace("/login"); return; }
    apiGet<Subject[]>("/api/subjects")
      .then((data) => {
        setSubjects(data);
        if (data.length > 0) setSelectedSubject(data[0].subject);
      })
      .catch(() => {});
  }, [router]);

  // 清理轮询
  useEffect(() => () => {
    if (pollRef.current) clearInterval(pollRef.current);
  }, []);

  // ===== 创卷 =====
  const handleCreate = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const resp = await apiPost<ExamCreateResponse>("/api/exams", {
        subject: selectedSubject || null,
        counts: counts,
      });
      setExam(resp);
      setAnswers({});
      setStep("answer");
    } catch (err) {
      setError(err instanceof Error ? err.message : "创卷失败");
    } finally {
      setLoading(false);
    }
  }, [counts, selectedSubject]);

  // ===== 暂存（防抖） =====
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const handleAnswerChange = useCallback((seq: number, value: string) => {
    setAnswers((prev) => ({ ...prev, [seq]: value }));
    // 防抖暂存
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(async () => {
      setSaving(true);
      try {
        await apiPut(`/api/exams/${exam?.id}/answers`, {
          answers: Object.entries({ ...answers, [seq]: value }).map(
            ([s, c]) => ({ seq: Number(s), content: c })
          ),
        });
        setSavedAt(new Date().toLocaleTimeString());
      } catch {
        // 暂存失败静默
      } finally {
        setSaving(false);
      }
    }, 1500);
  }, [exam, answers]);

  // ===== 交卷 =====
  const handleSubmit = useCallback(async () => {
    if (!exam) return;
    if (!confirm("确定交卷吗？交卷后不能再修改作答。")) return;
    setLoading(true);
    setError("");
    try {
      // 先同步暂存
      await apiPut(`/api/exams/${exam.id}/answers`, {
        answers: Object.entries(answers).map(([s, c]) => ({
          seq: Number(s), content: c,
        })),
      });
      const resp = await apiPost<ExamSubmitResponse>(`/api/exams/${exam.id}/submit`);
      setStep("result");
      // 立即拉一次详情
      const d = await apiGet<ExamDetailResponse>(`/api/exams/${exam.id}`);
      setDetail(d);
      // 有主观题需轮询
      if (resp.status === "grading") startPolling(exam.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "交卷失败");
    } finally {
      setLoading(false);
    }
  }, [exam, answers]);

  // ===== 轮询判卷结果 =====
  const startPolling = useCallback((examId: number) => {
    if (pollRef.current) clearInterval(pollRef.current);
    pollRef.current = setInterval(async () => {
      try {
        const d = await apiGet<ExamDetailResponse>(`/api/exams/${examId}`);
        setDetail(d);
        if (d.status === "graded") {
          if (pollRef.current) clearInterval(pollRef.current);
          pollRef.current = null;
        }
      } catch {
        // 轮询失败静默
      }
    }, 5000);
  }, []);

  // ===== 异议 =====
  const handleDispute = useCallback(async (seq: number) => {
    if (!exam) return;
    try {
      await apiPost(`/api/exams/${exam.id}/answers/${seq}/dispute`);
      alert("已提交异议，管理员将复核");
      // 刷新详情
      const d = await apiGet<ExamDetailResponse>(`/api/exams/${exam.id}`);
      setDetail(d);
    } catch (err) {
      alert(err instanceof Error ? err.message : "提交失败");
    }
  }, [exam]);

  // ===== 薄弱点问 AI =====
  const handleAskAi = useCallback((kpId: string) => {
    router.push(`/?ask=${encodeURIComponent("请讲解知识点 " + kpId)}&subject=${selectedSubject}`);
  }, [router, selectedSubject]);

  // ===== 重新考试 =====
  const handleRestart = useCallback(() => {
    setExam(null);
    setDetail(null);
    setAnswers({});
    setStep("setup");
    setError("");
  }, []);

  // ===== 渲染 =====

  if (step === "setup") {
    return (
      <div className="flex min-h-screen flex-col bg-gray-50">
        <Header title="在线考试" onBack={() => router.push("/")} />
        <main className="mx-auto w-full max-w-2xl flex-1 p-4 md:p-6">
          <h2 className="mb-4 text-xl font-semibold text-gray-900">组卷</h2>
          {error && <ErrorBanner text={error} />}
          <div className="space-y-4 rounded-xl border border-gray-200 bg-white p-5">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">科目</label>
              <select
                value={selectedSubject}
                onChange={(e) => setSelectedSubject(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
              >
                {subjects.map((s) => (
                  <option key={s.subject} value={s.subject}>{s.name}</option>
                ))}
              </select>
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium text-gray-700">题型与数量</label>
              <div className="grid grid-cols-2 gap-3">
                {QUESTION_TYPES.map((qt) => (
                  <div key={qt.key} className="flex items-center justify-between rounded-lg border border-gray-200 px-3 py-2">
                    <span className="text-sm text-gray-700">{qt.label}</span>
                    <input
                      type="number"
                      min={0}
                      max={qt.max}
                      value={counts[qt.key] ?? 0}
                      onChange={(e) =>
                        setCounts((prev) => ({
                          ...prev,
                          [qt.key]: Math.max(0, Math.min(qt.max, Number(e.target.value) || 0)),
                        }))
                      }
                      className="w-16 rounded-lg border border-gray-300 px-2 py-1 text-sm text-center outline-none focus:border-blue-500"
                    />
                  </div>
                ))}
              </div>
            </div>
          </div>
          <button
            onClick={handleCreate}
            disabled={loading || !selectedSubject}
            className="mt-4 w-full rounded-xl bg-blue-600 py-3 font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "组卷中…" : "开始考试"}
          </button>
        </main>
      </div>
    );
  }

  if (step === "answer" && exam) {
    return (
      <div className="flex min-h-screen flex-col bg-gray-50">
        <Header title={`考试 · ${exam.question_count} 题 / 满分 ${exam.total_score}`} onBack={() => router.push("/")} />
        {error && <ErrorBanner text={error} />}
        <main className="mx-auto w-full max-w-2xl flex-1 overflow-y-auto p-4 md:p-6">
          <div className="space-y-4">
            {exam.questions.map((q) => (
              <div key={q.seq} className="rounded-xl border border-gray-200 bg-white p-4">
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm font-medium text-gray-500">
                    第 {q.seq} 题 · {q.question_type} · {q.full_score} 分
                  </span>
                </div>
                {q.materials && (
                  <pre className="mb-3 whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-sm text-gray-700">{q.materials}</pre>
                )}
                {q.stem && <p className="mb-3 text-sm text-gray-900">{q.stem}</p>}
                {q.sub_questions && q.sub_questions.length > 0 && (
                  <ol className="mb-3 list-inside list-decimal space-y-1 text-sm text-gray-700">
                    {q.sub_questions.map((sq, i) => (
                      <li key={i} className="whitespace-pre-wrap">
                        {typeof sq === "string" ? sq : sq.question || JSON.stringify(sq)}
                      </li>
                    ))}
                  </ol>
                )}
                {q.options ? (
                  <div className="space-y-2">
                    {Object.entries(q.options).map(([key, val]) => {
                      const isMulti = q.question_type === "多选";
                      const selected = isMulti
                        ? (answers[q.seq] || "").includes(key)
                        : answers[q.seq] === key;
                      const handlePick = () => {
                        if (isMulti) {
                          // 多选：切换选中状态，答案按字母排序拼接（如 "ACD"）
                          const cur = answers[q.seq] || "";
                          const next = cur.includes(key)
                            ? cur.replace(key, "")
                            : (cur + key).split("").sort().join("");
                          handleAnswerChange(q.seq, next);
                        } else {
                          handleAnswerChange(q.seq, key);
                        }
                      };
                      return (
                        <label
                          key={key}
                          className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm transition-colors ${
                            selected
                              ? "border-blue-500 bg-blue-50 text-blue-700"
                              : "border-gray-200 hover:bg-gray-50"
                          }`}
                        >
                          <input
                            type={isMulti ? "checkbox" : "radio"}
                            name={`q-${q.seq}`}
                            checked={selected}
                            onChange={handlePick}
                            className="h-4 w-4 text-blue-600"
                          />
                          <span className="font-medium">{key}.</span>
                          <span className="text-gray-700">{val}</span>
                        </label>
                      );
                    })}
                  </div>
                ) : (
                  <textarea
                    value={answers[q.seq] ?? ""}
                    onChange={(e) => handleAnswerChange(q.seq, e.target.value)}
                    placeholder="在此输入你的解答…"
                    rows={6}
                    className="w-full resize-y rounded-lg border border-gray-300 px-3 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
                  />
                )}
              </div>
            ))}
          </div>
        </main>
        <div className="border-t border-gray-200 bg-white px-4 py-3">
          <div className="mx-auto flex max-w-2xl items-center justify-between">
            <span className="text-xs text-gray-400">
              {saving ? "暂存中…" : savedAt ? `已暂存 ${savedAt}` : "修改后自动暂存"}
            </span>
            <button
              onClick={handleSubmit}
              disabled={loading}
              className="rounded-xl bg-blue-600 px-6 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? "提交中…" : "交卷"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // step === "result"
  if (step === "result" && detail) {
    const isGrading = detail.status === "grading";
    return (
      <div className="flex min-h-screen flex-col bg-gray-50">
        <Header title="成绩单" onBack={() => router.push("/")} />
        <main className="mx-auto w-full max-w-2xl flex-1 overflow-y-auto p-4 md:p-6">
          {/* 总分 */}
          <div className="mb-4 rounded-xl border border-gray-200 bg-white p-5">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-gray-500">
                  {detail.question_count} 题 · 满分 {detail.total_score}
                </p>
                {isGrading ? (
                  <p className="mt-1 text-lg font-semibold text-amber-600">判卷中…</p>
                ) : (
                  <p className="mt-1 text-2xl font-bold text-gray-900">
                    {detail.obtained_score ?? 0} 分
                  </p>
                )}
              </div>
              {!isGrading && (
                <button
                  onClick={handleRestart}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
                >
                  再考一次
                </button>
              )}
            </div>
            {isGrading && (
              <p className="mt-2 text-sm text-gray-400">主观题正在由 AI 判卷，请稍候（每 5 秒自动刷新）</p>
            )}
          </div>

          {/* 掌握度 */}
          {!isGrading && detail.mastery && (
            <div className="mb-4 rounded-xl border border-gray-200 bg-white p-5">
              <h3 className="mb-3 text-sm font-semibold text-gray-900">知识点掌握度</h3>
              <div className="space-y-2">
                {detail.mastery.by_kp.map((kp) => (
                  <div key={kp.kp_id} className="flex items-center gap-2">
                    <span className="w-32 flex-shrink-0 truncate text-xs text-gray-500">{kp.kp_id}</span>
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-gray-100">
                      <div
                        className={`h-full ${kp.rate < 0.6 ? "bg-red-400" : "bg-green-400"}`}
                        style={{ width: `${Math.round(kp.rate * 100)}%` }}
                      />
                    </div>
                    <span className="w-10 text-right text-xs text-gray-500">{Math.round(kp.rate * 100)}%</span>
                  </div>
                ))}
              </div>
              {detail.mastery.weak_kps.length > 0 && (
                <div className="mt-4">
                  <p className="mb-2 text-xs font-medium text-red-500">薄弱知识点</p>
                  <div className="flex flex-wrap gap-2">
                    {detail.mastery.weak_kps.map((kp) => (
                      <button
                        key={kp.kp_id}
                        onClick={() => handleAskAi(kp.kp_id)}
                        className="rounded-full border border-red-200 bg-red-50 px-3 py-1 text-xs text-red-600 hover:bg-red-100"
                      >
                        {kp.kp_id} · 问 AI
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 逐题 */}
          <div className="space-y-4">
            {detail.answers.map((a) => {
              const reveal = !isGrading;
              return (
                <div key={a.seq} className="rounded-xl border border-gray-200 bg-white p-4">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="text-sm font-medium text-gray-500">
                      第 {a.seq} 题 · {a.question_type} · {a.full_score} 分
                    </span>
                    {reveal && a.score !== null && (
                      <span className={`text-sm font-semibold ${a.score >= a.full_score * 0.6 ? "text-green-600" : "text-red-500"}`}>
                        {a.score} / {a.full_score}
                      </span>
                    )}
                  </div>
                  {a.materials && (
                    <pre className="mb-2 whitespace-pre-wrap rounded-lg bg-gray-50 p-3 text-sm text-gray-700">{a.materials}</pre>
                  )}
                  {a.stem && <p className="mb-2 text-sm text-gray-900">{a.stem}</p>}
                  {a.options && (
                    <div className="mb-2 space-y-1">
                      {Object.entries(a.options).map(([key, val]) => (
                        <p
                          key={key}
                          className={`text-sm ${
                            reveal && a.correct_answer?.includes(key)
                              ? "font-medium text-green-700"
                              : "text-gray-600"
                          }`}
                        >
                          {key}. {val}
                        </p>
                      ))}
                    </div>
                  )}
                  <div className="space-y-1 text-sm">
                    <p className="text-gray-700">
                      <span className="text-gray-400">你的答案：</span>
                      {a.my_answer || "（未作答）"}
                    </p>
                    {reveal && a.correct_answer && (
                      <p className="text-green-700">
                        <span className="text-gray-400">参考答案：</span>{a.correct_answer}
                      </p>
                    )}
                    {reveal && a.explanation && (
                      <p className="text-gray-600">
                        <span className="text-gray-400">解析：</span>{a.explanation}
                      </p>
                    )}
                    {reveal && a.llm_reason && (
                      <p className="text-gray-500">
                        <span className="text-gray-400">判分理由：</span>{a.llm_reason}
                      </p>
                    )}
                  </div>
                  {reveal && a.question_type !== "单选" && a.question_type !== "多选" && (
                    <button
                      onClick={() => handleDispute(a.seq)}
                      className={`mt-3 rounded-lg border px-3 py-1 text-xs transition-colors ${
                        a.disputed
                          ? "border-amber-300 bg-amber-50 text-amber-600"
                          : "border-gray-300 text-gray-500 hover:bg-gray-50"
                      }`}
                    >
                      {a.disputed ? "已提交异议" : "我有异议"}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
        </main>
      </div>
    );
  }

  return null;
}

function Header({ title, onBack }: { title: string; onBack: () => void }) {
  return (
    <header className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3 md:px-6">
      <div className="flex items-center gap-3">
        <button onClick={onBack} className="rounded-lg p-1.5 text-gray-500 hover:bg-gray-100" title="返回">
          <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>
        <h1 className="text-lg font-semibold text-gray-900">{title}</h1>
      </div>
      <a href="/" className="rounded-lg px-3 py-1 text-sm text-blue-600 hover:bg-blue-50">返回对话</a>
    </header>
  );
}

function ErrorBanner({ text }: { text: string }) {
  return (
    <div className="mb-4 flex items-center justify-between rounded-lg bg-red-50 px-4 py-2 text-sm text-red-600">
      <span>{text}</span>
    </div>
  );
}
