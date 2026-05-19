"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { Fingerprint, ScanFace, Loader2, QrCode } from "lucide-react";
import { registerPasskey } from "@/lib/api";
import { enrollPasskey } from "@/lib/webauthn";
import type { PublicKeyCredentialCreationOptionsJSON } from "@simplewebauthn/browser";

type BiometricMethod = "faceid" | "touchid" | "qrcode";

export default function PasskeyEnrollment() {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [activeMethod, setActiveMethod] = useState<BiometricMethod | null>(null);
  const [error, setError] = useState("");
  const [email, setEmail] = useState("");
  // null = still detecting, true = biometrics available, false = not available
  const [platformAvailable, setPlatformAvailable] = useState<boolean | null>(null);

  useEffect(() => {
    const e = sessionStorage.getItem("pending_email");
    if (!e) {
      router.replace("/login");
    } else {
      setEmail(e);
    }

    if (typeof window !== "undefined" && window.PublicKeyCredential) {
      PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable()
        .then(setPlatformAvailable)
        .catch(() => setPlatformAvailable(false));
    } else {
      setPlatformAvailable(false);
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

      if (method === "qrcode") {
        // "cross-platform" is what forces Chrome/Brave on Linux to open its caBLE
        // (QR + Bluetooth) dialog instead of waiting for a USB security key.
        // requireResidentKey:false and userVerification:"preferred" are required
        // because some phones acting as cross-platform authenticators do not support
        // discoverable credentials, and we don't want to block them.
        options.authenticatorSelection = {
          authenticatorAttachment: "cross-platform",
          requireResidentKey: false,
          userVerification: "preferred",
        };
      }

      const credential = await enrollPasskey(options);
      const { token } = await registerPasskey(email, credential);
      localStorage.setItem("smartshop_token", token);
      sessionStorage.removeItem("passkey_options");
      sessionStorage.removeItem("pending_user_id");
      sessionStorage.removeItem("pending_email");
      sessionStorage.removeItem("register_email");
      router.push("/plan");
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
      <p className="text-sm text-gray-500 dark:text-gray-400">
        Choose how you want to secure your account. Your biometric data never
        leaves your device.
      </p>

      {error && <p className="text-red-500 text-sm">{error}</p>}

      {platformAvailable === null ? (
        <div className="flex justify-center py-4">
          <Loader2 className="animate-spin w-6 h-6 text-indigo-600" />
        </div>
      ) : (
        <div className="space-y-3">
          {platformAvailable ? (
            <>
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

              <div className="relative my-1">
                <div className="absolute inset-0 flex items-center">
                  <div className="w-full border-t border-gray-200 dark:border-gray-700" />
                </div>
                <div className="relative flex justify-center text-xs text-gray-400">
                  <span className="bg-white dark:bg-gray-900 px-2">or</span>
                </div>
              </div>
            </>
          ) : (
            <p className="text-sm text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950 rounded-lg px-4 py-3">
              Your device doesn&apos;t support biometric authentication. Use your
              phone to scan a QR code instead.
            </p>
          )}

          <button
            onClick={() => handleEnroll("qrcode")}
            disabled={loading}
            className="w-full bg-gray-100 dark:bg-gray-800 text-gray-800 dark:text-gray-200 rounded-lg py-3 font-semibold hover:bg-gray-200 dark:hover:bg-gray-700 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {activeMethod === "qrcode" && loading ? (
              <Loader2 className="animate-spin w-4 h-4" />
            ) : (
              <QrCode className="w-5 h-5" />
            )}
            {activeMethod === "qrcode" && loading
              ? "Waiting for QR scan…"
              : "Scan QR code with another device"}
          </button>
        </div>
      )}
    </div>
  );
}
