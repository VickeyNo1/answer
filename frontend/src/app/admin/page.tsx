"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { getRole, clearAuth } from "@/lib/auth";
import { StatsTab } from "@/components/admin/StatsTab";
import { StudentTab } from "@/components/admin/StudentTab";
import { ModelTab } from "@/components/admin/ModelTab";
import { OperationsTab } from "@/components/admin/OperationsTab";
import { ExamTab } from "@/components/admin/ExamTab";

type TabKey = "stats" | "students" | "models" | "operations" | "exams";

const TABS: { key: TabKey; label: string }[] = [
  { key: "stats", label: "统计概览" },
  { key: "students", label: "学生管理" },
  { key: "models", label: "大模型" },
  { key: "exams", label: "考试" },
  { key: "operations", label: "运营报表" },
];

export default function AdminPage() {
  const router = useRouter();
  const [activeTab, setActiveTab] = useState<TabKey>("stats");
  const [authorized, setAuthorized] = useState(false);

  useEffect(() => {
    if (getRole() !== "admin") {
      router.replace("/");
      return;
    }
    setAuthorized(true);
  }, [router]);

  function handleLogout() {
    clearAuth();
    router.replace("/login");
  }

  if (!authorized) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-gray-400">正在跳转...</p>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col bg-gray-50">
      {/* 顶栏 */}
      <header className="flex items-center justify-between border-b border-gray-200 bg-white px-6 py-3">
        <div className="flex items-center gap-6">
          <h1 className="text-lg font-semibold text-gray-900">管理后台</h1>
          <nav className="flex gap-1">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`rounded-lg px-4 py-1.5 text-sm font-medium transition-colors ${
                  activeTab === tab.key
                    ? "bg-blue-50 text-blue-600"
                    : "text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <a
            href="/"
            className="rounded-lg px-3 py-1 text-sm text-blue-600 transition-colors hover:bg-blue-50"
          >
            返回对话
          </a>
          <button
            onClick={handleLogout}
            className="rounded-lg px-3 py-1 text-sm text-gray-500 transition-colors hover:bg-gray-100"
          >
            退出
          </button>
        </div>
      </header>

      {/* 内容区 */}
      <main className="flex-1 overflow-y-auto p-6">
        {activeTab === "stats" && <StatsTab />}
        {activeTab === "students" && <StudentTab />}
        {activeTab === "models" && <ModelTab />}
        {activeTab === "exams" && <ExamTab />}
        {activeTab === "operations" && <OperationsTab />}
      </main>
    </div>
  );
}
