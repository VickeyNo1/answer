"use client";

import { useState, useEffect, useCallback } from "react";
import { apiGet, apiPost, apiPut, apiDelete } from "@/lib/api";
import type {
  ModelConfig,
  ModelConfigCreate,
  ModelConfigUpdate,
  UsageStats,
} from "@/types";

const PROVIDER_LABELS: Record<string, string> = {
  ali: "阿里百炼",
  deepseek: "DeepSeek",
};

export function ModelTab() {
  const [models, setModels] = useState<ModelConfig[]>([]);
  const [usage, setUsage] = useState<UsageStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<ModelConfig | null>(null);
  const [confirmDeleteId, setConfirmDeleteId] = useState<number | null>(null);

  const loadModels = useCallback(async () => {
    try {
      const data = await apiGet<ModelConfig[]>("/api/admin/models");
      setModels(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载模型失败");
    }
  }, []);

  const loadUsage = useCallback(async () => {
    try {
      const data = await apiGet<UsageStats>("/api/admin/models/usage?days=7");
      setUsage(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载用量失败");
    }
  }, []);

  const loadAll = useCallback(async () => {
    setLoading(true);
    await Promise.all([loadModels(), loadUsage()]);
    setLoading(false);
  }, [loadModels, loadUsage]);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  async function handleCreate(data: ModelConfigCreate) {
    try {
      await apiPost("/api/admin/models", data);
      setShowCreate(false);
      loadModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    }
  }

  async function handleUpdate(id: number, data: ModelConfigUpdate) {
    try {
      await apiPut(`/api/admin/models/${id}`, data);
      setEditing(null);
      loadModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : "修改失败");
    }
  }

  async function handleDelete(id: number) {
    try {
      await apiDelete(`/api/admin/models/${id}`);
      setConfirmDeleteId(null);
      loadModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  }

  async function handleActivate(id: number) {
    try {
      await apiPost(`/api/admin/models/${id}/activate`);
      loadModels();
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换失败");
    }
  }

  const maxDailyTokens = usage
    ? Math.max(1, ...usage.daily.map((d) => d.tokens))
    : 1;

  return (
    <div className="space-y-6">
      {/* 错误提示 */}
      {error && (
        <div className="flex items-center justify-between rounded-xl bg-red-50 px-4 py-2.5 text-sm text-red-600">
          <span>{error}</span>
          <button onClick={() => setError("")} className="text-red-400 hover:text-red-600">✕</button>
        </div>
      )}

      {/* 用量看板 */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCard label="今日 Tokens" value={usage ? formatNumber(usage.today_tokens) : "-"} />
        <StatCard label="今日费用" value={usage ? `¥${usage.today_cost.toFixed(4)}` : "-"} />
        <StatCard label="累计 Tokens" value={usage ? formatNumber(usage.total_tokens) : "-"} />
        <StatCard label="累计费用" value={usage ? `¥${usage.total_cost.toFixed(4)}` : "-"} />
      </div>

      {/* 最近趋势 + 按模型明细 */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {/* 最近 7 天趋势 */}
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <h3 className="mb-4 text-sm font-semibold text-gray-900">最近 7 天用量趋势</h3>
          {usage && usage.daily.length > 0 ? (
            <div className="flex items-end gap-2" style={{ height: 140 }}>
              {usage.daily.map((d) => (
                <div key={d.date} className="flex flex-1 flex-col items-center gap-1">
                  <div className="flex w-full flex-1 items-end">
                    <div
                      className="w-full rounded-t bg-blue-500 transition-all"
                      style={{ height: `${(d.tokens / maxDailyTokens) * 100}%` }}
                      title={`${d.tokens} tokens / ¥${d.cost.toFixed(4)}`}
                    ></div>
                  </div>
                  <span className="text-[10px] text-gray-400">{d.date.slice(5)}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="py-8 text-center text-sm text-gray-400">暂无用量数据</p>
          )}
        </div>

        {/* 按模型明细 */}
        <div className="rounded-xl border border-gray-200 bg-white p-4">
          <h3 className="mb-4 text-sm font-semibold text-gray-900">按模型用量明细</h3>
          {usage && usage.by_model.length > 0 ? (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-gray-500">
                  <th className="pb-2 font-medium">模型</th>
                  <th className="pb-2 font-medium text-right">Tokens</th>
                  <th className="pb-2 font-medium text-right">费用</th>
                </tr>
              </thead>
              <tbody>
                {usage.by_model.map((m) => (
                  <tr key={m.model_name} className="border-t border-gray-100">
                    <td className="py-2 text-gray-900">{m.model_name}</td>
                    <td className="py-2 text-right text-gray-600">{formatNumber(m.tokens)}</td>
                    <td className="py-2 text-right text-gray-600">¥{m.cost.toFixed(4)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="py-8 text-center text-sm text-gray-400">暂无用量数据</p>
          )}
        </div>
      </div>

      {/* 模型列表 */}
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">模型配置</h3>
          <button
            onClick={() => setShowCreate(true)}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            + 新增模型
          </button>
        </div>

        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-200 bg-gray-50 text-left text-gray-500">
                <th className="px-4 py-3 font-medium">模型名称</th>
                <th className="px-4 py-3 font-medium">提供方</th>
                <th className="px-4 py-3 font-medium">模型标识</th>
                <th className="px-4 py-3 font-medium text-right">输入单价</th>
                <th className="px-4 py-3 font-medium text-right">输出单价</th>
                <th className="px-4 py-3 font-medium text-center">状态</th>
                <th className="px-4 py-3 font-medium text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-400">加载中...</td>
                </tr>
              ) : models.length === 0 ? (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-gray-400">暂无模型配置</td>
                </tr>
              ) : (
                models.map((m) => (
                  <tr key={m.id} className="border-b border-gray-100 last:border-0 hover:bg-gray-50">
                    <td className="px-4 py-3 text-gray-900">{m.display_name}</td>
                    <td className="px-4 py-3 text-gray-600">{PROVIDER_LABELS[m.provider] || m.provider}</td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-500">{m.model_name}</td>
                    <td className="px-4 py-3 text-right text-gray-600">¥{m.price_in}/千</td>
                    <td className="px-4 py-3 text-right text-gray-600">¥{m.price_out}/千</td>
                    <td className="px-4 py-3 text-center">
                      {m.is_active ? (
                        <span className="rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-600">当前使用</span>
                      ) : !m.enabled ? (
                        <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-400">已禁用</span>
                      ) : (
                        <span className="rounded-full bg-gray-50 px-2 py-0.5 text-xs text-gray-500">可用</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center justify-end gap-2">
                        {!m.is_active && m.enabled && (
                          <button
                            onClick={() => handleActivate(m.id)}
                            className="rounded-lg px-3 py-1 text-sm text-green-600 hover:bg-green-50"
                          >
                            设为当前
                          </button>
                        )}
                        <button
                          onClick={() => setEditing(m)}
                          className="rounded-lg px-3 py-1 text-sm text-blue-600 hover:bg-blue-50"
                        >
                          编辑
                        </button>
                        {confirmDeleteId === m.id ? (
                          <>
                            <button
                              onClick={() => handleDelete(m.id)}
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
                            onClick={() => setConfirmDeleteId(m.id)}
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

      {/* 新增/编辑弹窗 */}
      {showCreate && (
        <ModelModal
          title="新增模型"
          onClose={() => setShowCreate(false)}
          onSubmit={(data) => handleCreate(data as ModelConfigCreate)}
        />
      )}
      {editing && (
        <ModelModal
          title="编辑模型"
          model={editing}
          onClose={() => setEditing(null)}
          onSubmit={(data) => handleUpdate(editing.id, data)}
        />
      )}
    </div>
  );
}

/** 统计卡片 */
function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-1 text-xl font-semibold text-gray-900">{value}</p>
    </div>
  );
}

/** 模型新增/编辑弹窗 */
function ModelModal({
  title,
  model,
  onClose,
  onSubmit,
}: {
  title: string;
  model?: ModelConfig;
  onClose: () => void;
  onSubmit: (data: ModelConfigCreate | ModelConfigUpdate) => void;
}) {
  const [provider, setProvider] = useState(model?.provider || "ali");
  const [modelName, setModelName] = useState(model?.model_name || "");
  const [displayName, setDisplayName] = useState(model?.display_name || "");
  const [priceIn, setPriceIn] = useState(String(model?.price_in ?? 0));
  const [priceOut, setPriceOut] = useState(String(model?.price_out ?? 0));
  const [enabled, setEnabled] = useState(model?.enabled ?? true);

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    onSubmit({
      provider,
      model_name: modelName,
      display_name: displayName,
      price_in: parseFloat(priceIn) || 0,
      price_out: parseFloat(priceOut) || 0,
      enabled,
    });
  }

  return (
    <Modal title={title} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <Field label="提供方" required>
          <select
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
          >
            <option value="ali">阿里百炼</option>
            <option value="deepseek">DeepSeek</option>
          </select>
        </Field>
        <Field label="显示名称" required>
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="如 通义千问 Plus"
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            required
          />
        </Field>
        <Field label="模型标识 (model_name)" required>
          <input
            type="text"
            value={modelName}
            onChange={(e) => setModelName(e.target.value)}
            placeholder="如 qwen-plus"
            className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            required
          />
        </Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="输入单价 (元/千token)">
            <input
              type="number"
              step="0.0001"
              value={priceIn}
              onChange={(e) => setPriceIn(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            />
          </Field>
          <Field label="输出单价 (元/千token)">
            <input
              type="number"
              step="0.0001"
              value={priceOut}
              onChange={(e) => setPriceOut(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-4 py-2 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-200"
            />
          </Field>
        </div>
        <div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
              className="rounded border-gray-300"
            />
            启用该模型
          </label>
        </div>
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

/** 数字千分位格式化 */
function formatNumber(n: number): string {
  return n.toLocaleString("zh-CN");
}
