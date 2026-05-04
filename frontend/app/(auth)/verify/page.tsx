"use client";

import { useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { sendOtp } from "@/lib/api";
import { Mail, Loader2 } from "lucide-react";

function VerifyInfo() {
  const searchParams = useSearchParams();
  const email = searchParams.get("email") ?? "";

  const [resending, setResending] = useState(false);
  const [resent, setResent] = useState(false);
  const [error, setError] = useState("");

  const handleResend = async () => {
    setResending(true);
    setResent(false);
    setError("");
    try {
      const raw = sessionStorage.getItem("pending_registration_data");
      const data = raw ? JSON.parse(raw) : {};
      await sendOtp({ email, ...data });
      setResent(true);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to resend email");
    } finally {
      setResending(false);
    }
  };

  return (
    <div className="text-center">
      <div className="flex justify-center mb-4">
        <Mail className="w-16 h-16 text-indigo-500" />
      </div>
      <h2 className="text-xl font-semibold mb-2">Check your email</h2>
      <p className="text-sm text-gray-500 mb-6">
        We sent a confirmation link to <strong>{email}</strong>.<br />
        Click the link to complete your registration.
      </p>
      {resent && (
        <p className="text-green-600 text-sm mb-4">Confirmation email resent!</p>
      )}
      {error && <p className="text-red-500 text-sm mb-4">{error}</p>}
      <button
        type="button"
        onClick={handleResend}
        disabled={resending}
        className="text-indigo-600 hover:underline text-sm flex items-center gap-1 mx-auto disabled:opacity-50"
      >
        {resending && <Loader2 className="animate-spin w-3 h-3" />}
        Resend confirmation email
      </button>
    </div>
  );
}

export default function VerifyPage() {
  return (
    <Suspense>
      <VerifyInfo />
    </Suspense>
  );
}
