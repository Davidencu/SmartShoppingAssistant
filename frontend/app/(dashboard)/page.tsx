import { createClient } from "@/lib/supabase/server";
import { getWallet } from "@/lib/api";
import BalanceDisplay from "@/components/wallet/BalanceDisplay";

export default async function DashboardPage() {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const token = session!.access_token;

  let availableCents = 0;
  try {
    const { wallet } = await getWallet(token);
    availableCents = wallet.available_cents;
  } catch {
    // wallet may not exist yet on first load after registration
  }

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font-bold text-slate-900">What would you like to buy?</h2>
        <p className="mt-1 text-sm text-slate-500">
          Describe a product or upload an image — the AI agent will find the best deal and check out for you.
        </p>
      </div>

      <BalanceDisplay availableCents={availableCents} />

      {availableCents === 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Your wallet is empty.{" "}
          <a href="/dashboard/wallet" className="font-semibold underline">
            Top up your balance
          </a>{" "}
          to start shopping.
        </div>
      )}

      <div className="rounded-xl border border-slate-200 bg-white p-1 shadow-sm">
        <textarea
          className="w-full resize-none rounded-lg p-4 text-sm text-slate-700 placeholder:text-slate-400 focus:outline-none"
          rows={4}
          placeholder="e.g. Sony WH-1000XM5 headphones, under $300, preferably from Amazon…"
          disabled={availableCents === 0}
        />
        <div className="flex justify-end border-t border-slate-100 px-4 py-2">
          <button
            className="rounded-lg bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-50"
            disabled={availableCents === 0}
          >
            Search &amp; Shop
          </button>
        </div>
      </div>
    </div>
  );
}
