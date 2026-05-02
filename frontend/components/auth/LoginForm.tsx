"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Fingerprint, Mail, Loader2, AlertCircle } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import {
  startAuthentication,
  browserSupportsWebAuthn,
} from "@simplewebauthn/browser";
import Link from "next/link";

type Step = "email" | "passkey" | "otp-sent";

export default function LoginForm() {
  const router = useRouter();
  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const supabase = createClient();

  async function handleEmailSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email.trim()) return;

    setLoading(true);
    try {
      const { data: factors } = await supabase.auth.mfa.listFactors();
      const hasPasskey =
        browserSupportsWebAuthn() &&
        (factors?.webauthn?.length ?? 0) > 0;

      if (hasPasskey) {
        setStep("passkey");
        await handlePasskeyLogin();
      } else {
        const { error: otpErr } = await supabase.auth.signInWithOtp({
          email,
          options: {
            shouldCreateUser: false,
            emailRedirectTo: `${window.location.origin}/auth/callback?next=/dashboard`,
          },
        });
        if (otpErr) throw otpErr;
        setStep("otp-sent");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  async function handlePasskeyLogin() {
    setLoading(true);
    setError(null);
    try {
      const { data: factors } = await supabase.auth.mfa.listFactors();
      const factor = factors?.webauthn?.[0];
      if (!factor) throw new Error("No passkey found for this account.");

      const { data: challenge, error: challengeErr } =
        await supabase.auth.mfa.challenge({ factorId: factor.id });
      if (challengeErr) throw challengeErr;

      const assertion = await startAuthentication({
        optionsJSON: (challenge as { webAuthn?: { requestOptions: PublicKeyCredentialRequestOptionsJSON } }).webAuthn?.requestOptions!,
      });

      const { error: verifyErr } = await supabase.auth.mfa.verify({
        factorId: factor.id,
        challengeId: challenge.id,
        code: JSON.stringify(assertion),
      });
      if (verifyErr) throw verifyErr;

      router.replace("/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Passkey authentication failed.");
      setStep("email");
    } finally {
      setLoading(false);
    }
  }

  if (step === "otp-sent") {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm text-center space-y-4">
        <Mail className="mx-auto h-10 w-10 text-indigo-500" />
        <h2 className="text-lg font-semibold text-slate-900">Check your inbox</h2>
        <p className="text-sm text-slate-500">
          We sent a magic link to <strong>{email}</strong>. Click it to sign in.
        </p>
        <button
          onClick={() => setStep("email")}
          className="text-sm text-indigo-600 hover:underline"
        >
          Use a different email
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Sign in</h2>
        <p className="mt-1 text-sm text-slate-500">
          Use your passkey or receive a magic link.
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <form onSubmit={handleEmailSubmit} className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-slate-700 mb-1">
            Email address
          </label>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
          />
        </div>

        <button
          type="submit"
          disabled={loading}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Fingerprint className="h-4 w-4" />
          )}
          {loading ? "Authenticating…" : "Continue"}
        </button>
      </form>

      <p className="text-center text-sm text-slate-500">
        No account yet?{" "}
        <Link href="/register" className="text-indigo-600 hover:underline">
          Create one
        </Link>
      </p>
    </div>
  );
}
