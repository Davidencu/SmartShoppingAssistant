import { createClient } from "@/lib/supabase/server";
import { getWallet } from "@/lib/api";
import BalanceDisplay from "@/components/wallet/BalanceDisplay";
import TopUpButton from "@/components/wallet/TopUpButton";
import type { WalletTransaction } from "@/lib/types";

function fmt(cents: number, currency = "USD") {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(
    cents / 100
  );
}

function TxnRow({ txn }: { txn: WalletTransaction }) {
  const isCredit = txn.type === "TOPUP" || txn.type === "REFUND";
  return (
    <div className="flex items-center justify-between py-3">
      <div>
        <p className="text-sm font-medium text-slate-800">{txn.type}</p>
        <p className="text-xs text-slate-400">
          {new Date(txn.created_at).toLocaleString()}
        </p>
      </div>
      <span
        className={`text-sm font-semibold ${
          isCredit ? "text-emerald-600" : "text-red-600"
        }`}
      >
        {isCredit ? "+" : "-"}
        {fmt(txn.amount_cents)}
      </span>
    </div>
  );
}

export default async function WalletPage() {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  const token = session!.access_token;
  const userId = session!.user.id;

  const { wallet, recent_transactions } = await getWallet(token);

  return (
    <div className="space-y-6">
      <h2 className="text-2xl font-bold text-slate-900">Wallet</h2>

      <div className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
        <BalanceDisplay availableCents={wallet.available_cents} />
        {wallet.frozen_cents > 0 && (
          <p className="mt-1 text-xs text-slate-500">
            {fmt(wallet.frozen_cents)} reserved for an active order
          </p>
        )}
        <div className="mt-4">
          <TopUpButton userId={userId} />
        </div>
      </div>

      <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-6 py-4">
          <h3 className="text-sm font-semibold text-slate-700">
            Recent transactions
          </h3>
        </div>
        <div className="divide-y divide-slate-100 px-6">
          {recent_transactions.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-400">
              No transactions yet
            </p>
          ) : (
            recent_transactions.map((txn) => (
              <TxnRow key={txn.id} txn={txn} />
            ))
          )}
        </div>
      </div>
    </div>
  );
}
