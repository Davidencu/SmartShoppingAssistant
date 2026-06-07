"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import ThemeToggle from "@/components/ThemeToggle";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("smartshop_token");
    if (!token) {
      router.replace("/login");
      return;
    }
    setReady(true);
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
        </div>
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push("/history")}
            className="text-base text-gray-600 dark:text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400"
          >
            History
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
