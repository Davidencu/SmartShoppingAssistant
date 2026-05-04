"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import BalanceDisplay from "@/components/wallet/BalanceDisplay";
import TopUpModal from "@/components/wallet/TopUpModal";
import { getBalance } from "@/lib/api";
import { Loader2 } from "lucide-react";

export default function WalletPage() {
  const router = useRouter();
  const [balance, setBalance] = useState<number | null>(null);
  const [currency, setCurrency] = useState("USD");
  const [loading, setLoading] = useState(true);
  const [showTopUp, setShowTopUp] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("smartshop_token");
    if (!token) {
      router.replace("/login");
      return;
    }
    getBalance(token)
      .then((w) => {
        setBalance(w.balance);
        setCurrency(w.currency);
      })
      .catch(() => {
        localStorage.removeItem("smartshop_token");
        router.replace("/login");
      })
      .finally(() => setLoading(false));
  }, [router]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="animate-spin w-8 h-8 text-indigo-600" />
      </div>
    );
  }

  return (
    <main className="min-h-screen bg-gray-50 flex flex-col items-center justify-center p-6">
      <div className="w-full max-w-md bg-white rounded-2xl shadow-xl p-8">
        <h1 className="text-2xl font-bold text-center text-indigo-700 mb-6">Your Wallet</h1>
        <BalanceDisplay balance={balance ?? 0} currency={currency} />
        <button
          onClick={() => setShowTopUp(true)}
          className="mt-6 w-full bg-indigo-600 text-white rounded-lg py-3 font-semibold hover:bg-indigo-700"
        >
          Top Up Wallet
        </button>
        {balance !== null && balance > 0 && (
          <button
            onClick={() => router.push("/dashboard")}
            className="mt-3 w-full border border-indigo-600 text-indigo-600 rounded-lg py-3 font-semibold hover:bg-indigo-50"
          >
            Go to Dashboard
          </button>
        )}
      </div>
      {showTopUp && <TopUpModal onClose={() => setShowTopUp(false)} />}
    </main>
  );
}
