"use client";

import { useSearchParams } from "next/navigation";
import { Mail } from "lucide-react";

export default function OtpVerifyForm() {
  const params = useSearchParams();
  const email = params.get("email") ?? "your inbox";

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm text-center space-y-4">
      <Mail className="mx-auto h-10 w-10 text-indigo-500" />
      <h2 className="text-lg font-semibold text-slate-900">Check your inbox</h2>
      <p className="text-sm text-slate-500">
        We sent a confirmation link to <strong>{email}</strong>.
        <br />
        Click it to continue — no code needed.
      </p>
      <p className="text-xs text-slate-400">
        The link expires in 1 hour. Check your spam folder if you don&apos;t see it.
      </p>
    </div>
  );
}
