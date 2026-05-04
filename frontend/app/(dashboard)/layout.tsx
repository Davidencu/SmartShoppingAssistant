"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getBalance } from "@/lib/api";
import { Loader2 } from "lucide-react";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("smartshop_token");
    if (!token) {
      router.replace("/login");
      return;
    }
    getBalance(token)
      .then((wallet) => {
        if (wallet.balance <= 0) {
          router.replace("/wallet");
        } else {
          setReady(true);
        }
      })
      .catch(() => {
        localStorage.removeItem("smartshop_token");
        router.replace("/login");
      });
  }, [router]);

  if (!ready) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="animate-spin w-8 h-8 text-indigo-600" />
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <nav className="bg-white border-b px-6 py-4 flex items-center justify-between">
        <span className="font-bold text-indigo-700 text-lg">SmartShop</span>
        <div className="flex items-center gap-4">
          <button
            onClick={() => router.push("/wallet")}
            className="text-sm text-indigo-600 hover:underline"
          >
            Wallet
          </button>
          <button
            onClick={() => {
              localStorage.removeItem("smartshop_token");
              router.replace("/login");
            }}
            className="text-sm text-gray-500 hover:text-red-500"
          >
            Sign out
          </button>
        </div>
      </nav>
      <div className="max-w-3xl mx-auto p-6">{children}</div>
    </main>
  );
}
