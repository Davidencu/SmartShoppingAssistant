"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Fingerprint, ShieldCheck, Loader2, AlertCircle } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import {
  startRegistration,
  browserSupportsWebAuthn,
} from "@simplewebauthn/browser";

export default function PasskeyEnrollment() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const supabase = createClient();

  async function handleEnroll() {
    setError(null);
    setLoading(true);

    try {
      if (!browserSupportsWebAuthn()) {
        throw new Error(
          "Your browser does not support passkeys. Please use a modern browser."
        );
      }

      const { data: enrollData, error: enrollErr } =
        await supabase.auth.mfa.enroll({
          factorType: "webauthn",
          friendlyName: "SmartShop Passkey",
        });
      if (enrollErr) throw enrollErr;

      const creationOptions = (
        enrollData as unknown as {
          webAuthn: { creationOptions: PublicKeyCredentialCreationOptionsJSON };
        }
      ).webAuthn?.creationOptions;

      const attestation = await startRegistration({
        optionsJSON: creationOptions,
      });

      const { data: challengeData, error: challengeErr } =
        await supabase.auth.mfa.challenge({ factorId: enrollData.id });
      if (challengeErr) throw challengeErr;

      const { error: verifyErr } = await supabase.auth.mfa.verify({
        factorId: enrollData.id,
        challengeId: challengeData.id,
        code: JSON.stringify(attestation),
      });
      if (verifyErr) throw verifyErr;

      await supabase.auth.updateUser({
        data: { passkey_enrolled: true },
      });

      router.replace("/dashboard/wallet");
    } catch (err: unknown) {
      if (
        err instanceof Error &&
        err.name === "NotAllowedError"
      ) {
        setError("Passkey setup was cancelled. Please try again.");
      } else {
        setError(
          err instanceof Error ? err.message : "Passkey setup failed. Please try again."
        );
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm space-y-6 text-center">
      <ShieldCheck className="mx-auto h-12 w-12 text-indigo-500" />
      <div>
        <h2 className="text-xl font-semibold text-slate-900">
          Set up your passkey
        </h2>
        <p className="mt-2 text-sm text-slate-500 max-w-sm mx-auto">
          A passkey uses your device&apos;s biometrics (Face ID, Touch ID, or PIN)
          to confirm purchases instantly — no password needed.
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 text-left">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <div className="space-y-3">
        <button
          onClick={handleEnroll}
          disabled={loading}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-3 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
        >
          {loading ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Fingerprint className="h-4 w-4" />
          )}
          {loading ? "Setting up…" : "Create passkey"}
        </button>

        <button
          onClick={() => router.replace("/dashboard")}
          disabled={loading}
          className="w-full text-sm text-slate-400 hover:text-slate-600"
        >
          Skip for now
        </button>
      </div>
    </div>
  );
}
