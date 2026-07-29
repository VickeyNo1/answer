"use client";

import { useState, useEffect } from "react";
import { apiGet } from "@/lib/api";
import type { KbStats, HotKp, PaginatedFeedbacks, FeedbackItem } from "@/types";

/** 运营报表 Tab：检索质量卡片 + 高频知识点 Top10 + 反馈明细表（纯表格数字，不引图表库） */
export function OperationsTab() {
  return (
    <div className="space-y-6">
      <KbStatsSection />
      <HotKpsSection />
      <FeedbacksSection />
    </div>
  );
}

/** 检索质量统计（GET /api/admin/kb/stats?days=） */
function KbStatsSection() {
  const [days, setDays] = useState(7);
  const [stats, setStats] = useState<KbStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    apiGet<KbStats>(`/api/admin/kb/stats?days=${days}`)
      .then((data) => {
        if (cancelled) return;
        setStats(data);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  const cards = stats
    ? [
        { label: "检索总量", value: String(stats.total) },
        { label: "空结果率", value: `${(stats.empty_rate * 100).toFixed(1)}%` },
        { label: "降级次数", value: String(stats.degraded_count) },
        { label: "平均耗时", value: `${stats.avg_elapsed_ms} ms` },
      ]
    : [];

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">检索质量</h2>
        <DaysSelector value={days} onChange={setDays} options={[7, 30]} />
      </div>

      {error && (
        <div className="rounded-xl bg-red-50 px-4 py-2.5 text-sm text-red-600">{error}</div>
      )}

      {loading ? (
        <p className="py-8 text-center text-sm text-gray-400">加载中...</p>
      ) : stats ? (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {cards.map((c) => (
              <div key={c.label} className="rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
                <p className="text-sm text-gray-500">{c.label}</p>
                <p className="mt-1 text-2xl font-bold text-gray-900">{c.value}</p>
              </div>
            ))}
          </div>

          {/* 按状态统计 */}
          <div className="flex flex-wrap gap-2">
            {Object.entries(stats.by_status).map(([status, count]) => (
              <span
                key={status}
                className="rounded-full bg-gray-100 px-3 py-1 text-xs text-gray-600"
              >
                {status}: {count}
              </span>
            ))}
          </div>

          {/* 按天明细 */}
          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-200 bg-gray-50 text-left text-gray-500">
                  <th className="px-4 py-2.5 font-medium">日期</th>
                  <th className="px-4 py-2.5 font-medium">检索次数</th>
                  <th className="px-4 py-2.5 font-medium">空结果</th>
                  <th className="px-4 py-2.5 font-medium">降级</th>
                </tr>
              </thead>
              <tbody>
                {stats.by_day.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-6 text-center text-gray-400">暂无数据</td>
                  </tr>
                ) : (
                  stats.by_day.map((d) => (
                    <tr key={d.date} className="border-b border-gray-100 last:border-0">
                      <td className="px-4 py-2.5 text-gray-900">{d.date}</td>
                      <td className="px-4 py-2.5 text-gray-700">{d.total}</td>
                      <td className="px-4 py-2.5 text-gray-700">{d.empty}</td>
                      <td className="px-4 py-2.5 text-gray-700">{d.degraded}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </section>
  );
}

/** 高频知识点 Top10（GET /api/admin/kb/hot-kps?days=&top=） */
function HotKpsSection() {
  const [days, setDays] = useState(30);
  const [kps, setKps] = useState<HotKp[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    apiGet<HotKp[]>(`/api/admin/kb/hot-kps?days=${days}&top=10`)
      .then((data) => {
        if (cancelled) return;
        setKps(data);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [days]);

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">高频知识点 Top10</h2>
        <DaysSelector value={days} onChange={setDays} options={[7, 30]} />
      </div>

      {error && (
        <div className="rounded-xl bg-red-50 px-4 py-2.5 text-sm text-red-600">{error}</div>
      )}

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50 text-left text-gray-500">
              <th className="px-4 py-2.5 font-medium">排名</th>
              <th className="px-4 py-2.5 font-medium">知识点编号</th>
              <th className="px-4 py-2.5 font-medium">命中次数</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={3} className="px-4 py-6 text-center text-gray-400">加载中...</td>
              </tr>
            ) : kps.length === 0 ? (
              <tr>
                <td colSpan={3} className="px-4 py-6 text-center text-gray-400">暂无数据</td>
              </tr>
            ) : (
              kps.map((kp, i) => (
                <tr key={kp.kp_id} className="border-b border-gray-100 last:border-0">
                  <td className="px-4 py-2.5 text-gray-500">{i + 1}</td>
                  <td className="px-4 py-2.5 font-mono text-gray-900">{kp.kp_id}</td>
                  <td className="px-4 py-2.5 text-gray-700">{kp.count}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

/** 反馈明细表（GET /api/admin/feedbacks?rating=&page=&page_size=） */
function FeedbacksSection() {
  const [rating, setRating] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize] = useState(20);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  // 展开查看回答全文的行 id
  const [expandedId, setExpandedId] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    if (rating) params.set("rating", rating);
    apiGet<PaginatedFeedbacks>(`/api/admin/feedbacks?${params.toString()}`)
      .then((data) => {
        if (cancelled) return;
        setItems(data.items);
        setTotal(data.total);
        setError("");
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "加载失败");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [page, pageSize, rating]);

  const totalPages = Math.ceil(total / pageSize);

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-semibold text-gray-900">反馈明细</h2>
        <select
          value={rating}
          onChange={(e) => {
            setRating(e.target.value);
            setPage(1);
          }}
          className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
        >
          <option value="">全部评价</option>
          <option value="up">👍 点赞</option>
          <option value="down">👎 点踩</option>
        </select>
      </div>

      {error && (
        <div className="rounded-xl bg-red-50 px-4 py-2.5 text-sm text-red-600">{error}</div>
      )}

      <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200 bg-gray-50 text-left text-gray-500">
              <th className="px-4 py-2.5 font-medium">时间</th>
              <th className="px-4 py-2.5 font-medium">学生</th>
              <th className="px-4 py-2.5 font-medium">评价</th>
              <th className="px-4 py-2.5 font-medium">理由</th>
              <th className="px-4 py-2.5 font-medium">提问</th>
              <th className="px-4 py-2.5 font-medium">知识点</th>
              <th className="px-4 py-2.5 font-medium text-right">回答</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-gray-400">加载中...</td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-gray-400">暂无反馈数据</td>
              </tr>
            ) : (
              items.map((f) => (
                <FeedbackRow
                  key={f.id}
                  item={f}
                  expanded={expandedId === f.id}
                  onToggle={() => setExpandedId(expandedId === f.id ? null : f.id)}
                />
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
    </section>
  );
}

/** 反馈明细行（可展开查看 AI 回答全文） */
function FeedbackRow({
  item,
  expanded,
  onToggle,
}: {
  item: FeedbackItem;
  expanded: boolean;
  onToggle: () => void;
}) {
  return (
    <>
      <tr className="border-b border-gray-100 last:border-0 hover:bg-gray-50">
        <td className="whitespace-nowrap px-4 py-2.5 text-gray-500">{item.created_at}</td>
        <td className="whitespace-nowrap px-4 py-2.5 text-gray-900">
          {item.student_name}（{item.student_id}）
        </td>
        <td className="px-4 py-2.5">
          {item.rating === "up" ? (
            <span className="text-green-600">👍</span>
          ) : (
            <span className="text-red-500">👎</span>
          )}
        </td>
        <td className="max-w-[12rem] px-4 py-2.5 text-gray-700">
          {item.reason || <span className="text-gray-300">—</span>}
        </td>
        <td className="max-w-[14rem] truncate px-4 py-2.5 text-gray-700" title={item.question ?? undefined}>
          {item.question || <span className="text-gray-300">—</span>}
        </td>
        <td className="px-4 py-2.5">
          <div className="flex flex-wrap gap-1">
            {item.knowledge_point_ids.length === 0 ? (
              <span className="text-gray-300">—</span>
            ) : (
              item.knowledge_point_ids.map((kp) => (
                <span key={kp} className="rounded bg-blue-50 px-1.5 py-0.5 font-mono text-xs text-blue-600">
                  {kp}
                </span>
              ))
            )}
          </div>
        </td>
        <td className="px-4 py-2.5 text-right">
          <button
            onClick={onToggle}
            className="rounded-lg px-3 py-1 text-sm text-blue-600 hover:bg-blue-50"
          >
            {expanded ? "收起" : "查看"}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr className="border-b border-gray-100 bg-gray-50 last:border-0">
          <td colSpan={7} className="px-4 py-3">
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
              {item.answer}
            </p>
          </td>
        </tr>
      )}
    </>
  );
}

/** 天数筛选按钮组 */
function DaysSelector({
  value,
  onChange,
  options,
}: {
  value: number;
  onChange: (days: number) => void;
  options: number[];
}) {
  return (
    <div className="flex gap-1">
      {options.map((d) => (
        <button
          key={d}
          onClick={() => onChange(d)}
          className={`rounded-lg px-3 py-1 text-sm transition-colors ${
            value === d
              ? "bg-blue-50 font-medium text-blue-600"
              : "text-gray-500 hover:bg-gray-100"
          }`}
        >
          近 {d} 天
        </button>
      ))}
    </div>
  );
}
