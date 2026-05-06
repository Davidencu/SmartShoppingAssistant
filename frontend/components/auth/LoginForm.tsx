"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Fingerprint, Loader2 } from "lucide-react";
import { checkEmail, getPasskeyChallenge, verifyPasskey } from "@/lib/api";
import { authenticatePasskey } from "@/lib/webauthn";
import type { PublicKeyCredentialRequestOptionsJSON } from "@simplewebauthn/browser";

export default function LoginForm() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [emailError, setEmailError] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [step, setStep] = useState<"email" | "passkey">("email");

  const validateEmail = (v: string) => {
    if (!v) return "Email is required";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v))
      return "Enter a valid email (user@domain.com)";
    return "";
  };

  const handleEmailSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const err = validateEmail(email);
    if (err) {
      setEmailError(err);
      return;
    }
    setEmailError("");
    setLoading(true);
    setError("");
    try {
      const { exists } = await checkEmail(email);
      if (exists) {
        setStep("passkey");
        await triggerPasskeyAuth();
      } else {
        sessionStorage.setItem("register_email", email);
        router.push("/register");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setStep("email");
    } finally {
      setLoading(false);
    }
  };

  const triggerPasskeyAuth = async () => {
    setLoading(true);
    setError("");
    try {
      const { options } = await getPasskeyChallenge(email);
      const credential = await authenticatePasskey(
        options as PublicKeyCredentialRequestOptionsJSON
      );
      const { token } = await verifyPasskey(email, credential);
      localStorage.setItem("smartshop_token", token);
      router.push("/dashboard");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Authentication failed");
      setStep("email");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <h2 className="text-xl font-semibold mb-6 text-center">Sign in</h2>

      {step === "email" ? (
        <form onSubmit={handleEmailSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
              Email address
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                if (emailError) setEmailError(validateEmail(e.target.value));
              }}
              placeholder="you@example.com"
              className={`w-full border rounded-lg px-4 py-3 focus:outline-none focus:ring-2 focus:ring-indigo-400 dark:bg-gray-700 dark:text-white dark:placeholder-gray-400 ${
                emailError ? "border-red-400" : "border-gray-300 dark:border-gray-600"
              }`}
            />
            {emailError && (
              <p className="text-red-500 text-xs mt-1">{emailError}</p>
            )}
          </div>

          {error && <p className="text-red-500 text-sm text-center">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-indigo-600 text-white rounded-lg py-3 font-semibold hover:bg-indigo-700 disabled:opacity-50 flex items-center justify-center gap-2"
          >
            {loading && <Loader2 className="animate-spin w-4 h-4" />}
            Continue
          </button>

          <p className="text-center text-sm text-gray-500 dark:text-gray-400">
            No account?{" "}
            <button
              type="button"
              onClick={() => router.push("/register")}
              className="text-indigo-600 hover:underline"
            >
              Sign up
            </button>
          </p>
        </form>
      ) : (
        <div className="text-center space-y-6">
          <Fingerprint className="mx-auto w-20 h-20 text-indigo-500" />
          <p className="text-gray-700 dark:text-gray-200 font-medium">
            Authenticating with Face ID / Touch ID
          </p>
          <p className="text-sm text-gray-500 dark:text-gray-400">{email}</p>

          {error && <p className="text-red-500 text-sm">{error}</p>}

          {error && (
            <button
              onClick={triggerPasskeyAuth}
              disabled={loading}
              className="w-full bg-indigo-600 text-white rounded-lg py-3 font-semibold hover:bg-indigo-700 disabled:opacity-50 flex items-center justify-center gap-2"
            >
              {loading && <Loader2 className="animate-spin w-4 h-4" />}
              Try again
            </button>
          )}

          {loading && <Loader2 className="animate-spin w-6 h-6 text-indigo-500 mx-auto" />}
        </div>
      )}
    </div>
  );
}
