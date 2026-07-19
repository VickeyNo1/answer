/**
 * Token 存取工具
 * 管理 localStorage 中的 JWT Token 和用户角色
 */

const TOKEN_KEY = "token";
const ROLE_KEY = "role";

/** 获取 Token */
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

/** 存储 Token */
export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
}

/** 获取用户角色 */
export function getRole(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(ROLE_KEY);
}

/** 存储用户角色 */
export function setRole(role: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(ROLE_KEY, role);
}

/** 清除 Token 和角色（登出） */
export function clearAuth(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ROLE_KEY);
}

/** 判断是否已登录 */
export function isAuthenticated(): boolean {
  return getToken() !== null;
}

/** 判断是否为管理员 */
export function isAdmin(): boolean {
  return getRole() === "admin";
}
