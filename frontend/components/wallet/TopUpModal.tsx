"use client";

import { useState } from "react";
import { X, Loader2 } from "lucide-react";
import { createCheckout } from "@/lib/api";

const AMOUNTS = [10, 25, 40, 50, 80, 100] as const;
type Amount = (typeof AMOUNTS)[number];

interface Props {
  onClose: () => void;
}

export default function TopUpModal({ onClose }: Props) {
  const [selected, setSelected] = useState<Amount | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleTopUp = async () => {
    if (!selected) return;
    const token = localStorage.getItem("smartshop_token");
    if (!token) return;
    setLoading(true);
    setError("");
    try {
      const { checkout_url } = await createCheckout(selected, token);
      window.location.href = checkout_url;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create checkout");
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-sm p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-bold text-gray-800">Top up wallet</h3>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-600"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        <p className="text-sm text-gray-500 mb-4">Select an amount (USD)</p>

        <div className="grid grid-cols-3 gap-3 mb-4">
          {AMOUNTS.map((amt) => (
            <button
              key={amt}
              onClick={() => setSelected(amt)}
              className={`py-3 rounded-xl font-semibold border-2 transition-colors ${
                selected === amt
                  ? "border-indigo-600 bg-indigo-600 text-white"
                  : "border-gray-200 text-gray-700 hover:border-indigo-400"
              }`}
            >
              ${amt}
            </button>
          ))}
        </div>

        {error && (
          <p className="text-red-500 text-sm mb-3 text-center">{error}</p>
        )}

        <button
          onClick={handleTopUp}
          disabled={!selected || loading}
          className="w-full bg-indigo-600 text-white rounded-lg py-3 font-semibold hover:bg-indigo-700 disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {loading && <Loader2 className="animate-spin w-4 h-4" />}
          {selected ? `Top up $${selected}` : "Select an amount"}
        </button>
      </div>
    </div>
  );
}
