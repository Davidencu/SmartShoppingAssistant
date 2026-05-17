"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Zap } from "lucide-react";
import ThemeToggle from "@/components/ThemeToggle";
import { getPlanStatus, ApiError } from "@/lib/api";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [plan, setPlan] = useState<"free" | "pro" | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("smartshop_token");
    if (!token) {
      router.replace("/login");
      return;
    }
    setReady(true);
    getPlanStatus(token)
      .then(({ plan }) => setPlan(plan as "free" | "pro"))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          localStorage.removeItem("smartshop_token");
          router.replace("/login");
        }
      });
  }, [router]);

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <Loader2 className="animate-spin w-8 h-8 text-indigo-600" />
      </div>
    );
  }

  return (
    <main className="h-screen flex flex-col bg-gray-50 dark:bg-gray-900">
      <nav className="shrink-0 bg-white dark:bg-gray-800 border-b dark:border-gray-700 px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="font-bold text-indigo-700 dark:text-indigo-400 text-xl">SmartShop</span>
          {plan === "pro" && (
            <span
              data-testid="plan-badge"
              className="flex items-center gap-1.5 text-sm font-semibold px-3 py-1 rounded-full bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300"
            >
              <Zap className="w-3.5 h-3.5" /> Pro
            </span>
          )}
          {plan === "free" && (
            <span
              data-testid="plan-badge"
              className="text-sm font-medium px-3 py-1 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400"
            >
              Free
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push("/history")}
            className="text-base text-gray-600 dark:text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400"
          >
            History
          </button>
          <button
            onClick={() => router.push("/plan")}
            className="text-base text-indigo-600 dark:text-indigo-400 hover:underline"
          >
            Plan
          </button>
          <ThemeToggle />
          <button
            onClick={() => {
              localStorage.removeItem("smartshop_token");
              router.replace("/login");
            }}
            className="text-base text-gray-500 dark:text-gray-400 hover:text-red-500 dark:hover:text-red-400"
          >
            Sign out
          </button>
        </div>
      </nav>
      <div className="flex-1 overflow-hidden">
        {children}
      </div>
    </main>
  );
}
