"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { isAuthenticated } from "@/lib/auth";

/**
 * 路由守卫组件
 * - /login 页面不需要认证
 * - 其他页面未登录时自动跳转 /login
 */
export function AuthGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    const isLoginPage = pathname === "/login";

    if (!isLoginPage && !isAuthenticated()) {
      router.replace("/login");
      return;
    }

    if (isLoginPage && isAuthenticated()) {
      router.replace("/");
      return;
    }

    setChecked(true);
  }, [pathname, router]);

  // 登录页不需要等待检查
  if (pathname === "/login") {
    return <>{children}</>;
  }

  // 未检查完成时显示加载状态
  if (!checked) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <div className="text-gray-400">加载中...</div>
      </div>
    );
  }

  return <>{children}</>;
}
