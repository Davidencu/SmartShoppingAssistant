"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, Zap } from "lucide-react";
import ThemeToggle from "@/components/ThemeToggle";
import { getPlanStatus } from "@/lib/api";

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
      .catch(() => {});
  }, [router]);

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
        <Loader2 className="animate-spin w-8 h-8 text-indigo-600" />
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-gray-50 dark:bg-gray-900">
      <nav className="bg-white dark:bg-gray-800 border-b dark:border-gray-700 px-6 py-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-bold text-indigo-700 dark:text-indigo-400 text-lg">SmartShop</span>
          {plan === "pro" && (
            <span
              data-testid="plan-badge"
              className="flex items-center gap-1 text-xs font-semibold px-2.5 py-0.5 rounded-full bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300"
            >
              <Zap className="w-3 h-3" /> Pro
            </span>
          )}
          {plan === "free" && (
            <span
              data-testid="plan-badge"
              className="text-xs font-medium px-2.5 py-0.5 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400"
            >
              Free
            </span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => router.push("/plan")}
            className="text-sm text-indigo-600 dark:text-indigo-400 hover:underline px-2"
          >
            Plan
          </button>
          <ThemeToggle />
          <button
            onClick={() => {
              localStorage.removeItem("smartshop_token");
              router.replace("/login");
            }}
            className="text-sm text-gray-500 dark:text-gray-400 hover:text-red-500 dark:hover:text-red-400"
          >
            Sign out
          </button>
        </div>
      </nav>
      <div className="max-w-3xl mx-auto p-6">{children}</div>
    </main>
  );
}
