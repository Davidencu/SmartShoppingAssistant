"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Fingerprint, ScanFace, Loader2 } from "lucide-react";
import { registerPasskey } from "@/lib/api";
import { enrollPasskey } from "@/lib/webauthn";
import type { PublicKeyCredentialCreationOptionsJSON } from "@simplewebauthn/browser";

type BiometricMethod = "faceid" | "touchid";

export default function PasskeyEnrollment() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [activeMethod, setActiveMethod] = useState<BiometricMethod | null>(null);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");

  useEffect(() => {
    const e = sessionStorage.getItem("pending_email");
    if (!e) {
      router.replace("/login");
    } else {
      setEmail(e);
    }
  }, [router]);

  const handleEnroll = async (method: BiometricMethod) => {
    setLoading(true);
    setActiveMethod(method);
    setError("");
    try {
      const raw = sessionStorage.getItem("passkey_options");
      if (!raw) throw new Error("No passkey options found. Please start again.");
      const options = JSON.parse(raw) as PublicKeyCredentialCreationOptionsJSON;
      const credential = await enrollPasskey(options);
      const { token } = await registerPasskey(email, credential);
      localStorage.setItem("smartshop_token", token);
      sessionStorage.removeItem("passkey_options");
      sessionStorage.removeItem("pending_user_id");
      sessionStorage.removeItem("pending_email");
      sessionStorage.removeItem("register_email");
      router.push("/wallet");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Enrollment failed. Please try again.");
      setActiveMethod(null);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="text-center space-y-6">
      <h2 className="text-xl font-semibold">Set up your passkey</h2>
      <p className="text-sm text-gray-500">
        Choose how you want to secure your account. Your biometric data never
        leaves your device.
      </p>

      {error && <p className="text-red-500 text-sm">{error}</p>}

      <div className="space-y-3">
        <button
          onClick={() => handleEnroll("faceid")}
          disabled={loading}
          className="w-full bg-indigo-600 text-white rounded-lg py-3 font-semibold hover:bg-indigo-700 disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {activeMethod === "faceid" && loading ? (
            <Loader2 className="animate-spin w-4 h-4" />
          ) : (
            <ScanFace className="w-5 h-5" />
          )}
          {activeMethod === "faceid" && loading ? "Setting up Face ID…" : "Set up with Face ID"}
        </button>

        <button
          onClick={() => handleEnroll("touchid")}
          disabled={loading}
          className="w-full bg-indigo-600 text-white rounded-lg py-3 font-semibold hover:bg-indigo-700 disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {activeMethod === "touchid" && loading ? (
            <Loader2 className="animate-spin w-4 h-4" />
          ) : (
            <Fingerprint className="w-5 h-5" />
          )}
          {activeMethod === "touchid" && loading
            ? "Setting up Touch ID…"
            : "Set up with Touch ID"}
        </button>
      </div>
    </div>
  );
}
