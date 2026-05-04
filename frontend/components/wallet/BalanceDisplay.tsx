import { Wallet } from "lucide-react";

interface Props {
  balance: number;
  currency: string;
}

export default function BalanceDisplay({ balance, currency }: Props) {
  const formatted = new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
  }).format(balance);

  return (
    <div className="flex flex-col items-center gap-2 py-6 bg-indigo-50 rounded-xl">
      <Wallet className="w-8 h-8 text-indigo-500" />
      <span className="text-4xl font-bold text-indigo-700">{formatted}</span>
      {balance <= 0 && (
        <p className="text-sm text-amber-600 font-medium mt-1">
          Top up your wallet to start shopping
        </p>
      )}
    </div>
  );
}
