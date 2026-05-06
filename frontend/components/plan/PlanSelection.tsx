"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Loader2, Zap } from "lucide-react";
import { selectFreePlan, createProCheckout } from "@/lib/api";

export default function PlanSelection() {
  const router = useRouter();
  const [loading, setLoading] = useState<"free" | "pro" | null>(null);
  const [error, setError] = useState("");

  const handleFree = async () => {
    setLoading("free");
    setError("");
    try {
      const token = localStorage.getItem("smartshop_token") ?? "";
      await selectFreePlan(token);
      router.push("/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setLoading(null);
    }
  };

  const handlePro = async () => {
    setLoading("pro");
    setError("");
    try {
      const token = localStorage.getItem("smartshop_token") ?? "";
      const { checkout_url } = await createProCheckout(token);
      window.location.href = checkout_url;
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setLoading(null);
    }
  };

  return (
    <div className="space-y-6">
      <div className="text-center">
        <h2 className="text-xl font-semibold">Choose your plan</h2>
        <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
          You can upgrade anytime. No credit card required for Free.
        </p>
      </div>

      {error && <p className="text-red-500 text-sm text-center">{error}</p>}

      <div className="grid grid-cols-1 gap-4">
        <div className="border dark:border-gray-700 rounded-xl p-5 hover:border-indigo-400 dark:hover:border-indigo-500 transition-colors dark:bg-gray-800">
          <div className="flex items-start justify-between">
            <div>
              <h3 className="font-bold text-lg">Free</h3>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                2 automated checkout sessions included
              </p>
              <ul className="mt-3 space-y-1 text-sm text-gray-600 dark:text-gray-300">
                <li className="flex items-center gap-2">
                  <Check className="w-4 h-4 text-green-500" /> Unlimited product searches
                </li>
                <li className="flex items-center gap-2">
                  <Check className="w-4 h-4 text-green-500" /> 2 automated checkouts
                </li>
                <li className="flex items-center gap-2">
                  <Check className="w-4 h-4 text-green-500" /> Manual checkout link after limit
                </li>
              </ul>
            </div>
            <span className="text-2xl font-bold">Free</span>
          </div>
          <button
            onClick={handleFree}
            disabled={loading !== null}
            className="mt-4 w-full border border-indigo-600 text-indigo-600 dark:text-indigo-400 dark:border-indigo-400 rounded-lg py-2 font-semibold hover:bg-indigo-50 dark:hover:bg-indigo-900/30 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {loading === "free" && <Loader2 className="animate-spin w-4 h-4" />}
            Get started free
          </button>
        </div>

        <div className="border-2 border-indigo-600 dark:border-indigo-500 rounded-xl p-5 bg-indigo-50 dark:bg-indigo-900/20">
          <div className="flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="font-bold text-lg">Pro</h3>
                <span className="bg-indigo-600 text-white text-xs px-2 py-0.5 rounded-full">
                  Recommended
                </span>
              </div>
              <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">
                Unlimited automated checkouts
              </p>
              <ul className="mt-3 space-y-1 text-sm text-gray-600 dark:text-gray-300">
                <li className="flex items-center gap-2">
                  <Check className="w-4 h-4 text-green-500" /> Unlimited product searches
                </li>
                <li className="flex items-center gap-2">
                  <Zap className="w-4 h-4 text-indigo-500" /> Unlimited automated checkouts
                </li>
                <li className="flex items-center gap-2">
                  <Check className="w-4 h-4 text-green-500" /> Priority support
                </li>
              </ul>
            </div>
            <div className="text-right">
                <span className="text-2xl font-bold">44.99 RON</span>
                <p className="text-xs text-gray-500 dark:text-gray-400">/lună</p>
              </div>
          </div>
          <button
            onClick={handlePro}
            disabled={loading !== null}
            className="mt-4 w-full bg-indigo-600 text-white rounded-lg py-2 font-semibold hover:bg-indigo-700 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {loading === "pro" && <Loader2 className="animate-spin w-4 h-4" />}
            Upgrade to Pro
          </button>
        </div>
      </div>
    </div>
  );
}
