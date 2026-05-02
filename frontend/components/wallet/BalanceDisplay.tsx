import { Wallet } from "lucide-react";

interface Props {
  availableCents: number;
  currency?: string;
}

export default function BalanceDisplay({
  availableCents,
  currency = "USD",
}: Props) {
  const formatted = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(availableCents / 100);

  return (
    <div className="flex items-center gap-3">
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-indigo-100">
        <Wallet className="h-5 w-5 text-indigo-600" />
      </div>
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-slate-400">
          Available balance
        </p>
        <p className="text-2xl font-bold text-slate-900">{formatted}</p>
      </div>
    </div>
  );
}
