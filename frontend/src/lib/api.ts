/**
 * API 请求封装
 * 自动附加 JWT Token，401 时自动跳转登录页
 */
import { getToken, clearAuth } from "./auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

/** 获取 API 基础地址 */
export function getApiBase(): string {
  return API_BASE;
}

/**
 * 统一请求函数
 * 自动附加 JWT Token 到 Header
 * 401 响应时自动清除 Token 并跳转登录页
 */
export async function apiFetch(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const token = getToken();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) || {}),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  // 401: Token 过期或无效，清除并跳转登录
  if (res.status === 401) {
    clearAuth();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("登录已过期，请重新登录");
  }

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(error.detail || `请求失败 (${res.status})`);
  }

  return res;
}

/**
 * GET 请求并解析 JSON
 */
export async function apiGet<T>(path: string): Promise<T> {
  const res = await apiFetch(path);
  return res.json();
}

/**
 * POST 请求并发送 JSON，解析 JSON 响应
 */
export async function apiPost<T>(
  path: string,
  data?: unknown
): Promise<T> {
  const res = await apiFetch(path, {
    method: "POST",
    body: data ? JSON.stringify(data) : undefined,
  });
  return res.json();
}

/**
 * PUT 请求并发送 JSON，解析 JSON 响应
 */
export async function apiPut<T>(
  path: string,
  data?: unknown
): Promise<T> {
  const res = await apiFetch(path, {
    method: "PUT",
    body: data ? JSON.stringify(data) : undefined,
  });
  return res.json();
}

/**
 * DELETE 请求，解析 JSON 响应
 */
export async function apiDelete<T>(path: string): Promise<T> {
  const res = await apiFetch(path, {
    method: "DELETE",
  });
  return res.json();
}

/**
 * 文件上传请求（不设置 Content-Type，使用 FormData 自动设置）
 */
export async function apiUpload<T>(
  path: string,
  formData: FormData
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers,
    body: formData,
  });

  if (res.status === 401) {
    clearAuth();
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("登录已过期，请重新登录");
  }

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "上传失败" }));
    throw new Error(error.detail || `上传失败 (${res.status})`);
  }

  return res.json();
}
