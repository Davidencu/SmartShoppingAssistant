"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { sendOtp, ApiError } from "@/lib/api";

const COUNTRY_CODES = [
  { code: "+1", label: "🇺🇸 +1 (US/CA)" },
  { code: "+44", label: "🇬🇧 +44 (UK)" },
  { code: "+40", label: "🇷🇴 +40 (RO)" },
  { code: "+49", label: "🇩🇪 +49 (DE)" },
  { code: "+33", label: "🇫🇷 +33 (FR)" },
  { code: "+39", label: "🇮🇹 +39 (IT)" },
  { code: "+34", label: "🇪🇸 +34 (ES)" },
  { code: "+31", label: "🇳🇱 +31 (NL)" },
  { code: "+48", label: "🇵🇱 +48 (PL)" },
  { code: "+7", label: "🇷🇺 +7 (RU)" },
  { code: "+81", label: "🇯🇵 +81 (JP)" },
  { code: "+86", label: "🇨🇳 +86 (CN)" },
  { code: "+91", label: "🇮🇳 +91 (IN)" },
  { code: "+55", label: "🇧🇷 +55 (BR)" },
  { code: "+52", label: "🇲🇽 +52 (MX)" },
  { code: "+61", label: "🇦🇺 +61 (AU)" },
  { code: "+82", label: "🇰🇷 +82 (KR)" },
  { code: "+971", label: "🇦🇪 +971 (UAE)" },
  { code: "+27", label: "🇿🇦 +27 (ZA)" },
  { code: "+20", label: "🇪🇬 +20 (EG)" },
] as const;

interface FormState {
  email: string;
  phone: string;
  countryCode: string;
  city: string;
  state: string;
  country: string;
}

interface Errors {
  email?: string;
  phone?: string;
  city?: string;
  country?: string;
}

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export default function RegisterForm() {
  const router = useRouter();

  const prefilled =
    typeof window !== "undefined"
      ? (sessionStorage.getItem("register_email") ?? "")
      : "";

  const [form, setForm] = useState<FormState>({
    email: prefilled,
    phone: "",
    countryCode: "+40",
    city: "",
    state: "",
    country: "",
  });
  const [errors, setErrors] = useState<Errors>({});
  const [loading, setLoading] = useState(false);
  const [globalError, setGlobalError] = useState("");
  const [alreadyRegistered, setAlreadyRegistered] = useState(false);

  const validate = (): Errors => {
    const e: Errors = {};
    if (!form.email.trim() || !EMAIL_RE.test(form.email.trim()))
      e.email = "Enter a valid email address (user@domain.com)";
    if (!form.phone.trim() || !/^\d{6,14}$/.test(form.phone.trim()))
      e.phone = "Enter 6–14 digits (without country code)";
    if (!form.city.trim()) e.city = "City is required";
    if (!form.country.trim()) e.country = "Country is required";
    return e;
  };

  const setField =
    (field: keyof FormState) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
      setForm((f) => ({ ...f, [field]: e.target.value }));
      if (errors[field as keyof Errors])
        setErrors((er) => ({ ...er, [field]: undefined }));
      if (field === "email") setAlreadyRegistered(false);
    };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const errs = validate();
    if (Object.keys(errs).length) {
      setErrors(errs);
      return;
    }
    setLoading(true);
    setGlobalError("");
    setAlreadyRegistered(false);
    const email = form.email.trim().toLowerCase();
    const pendingData = {
      phone: `${form.countryCode}${form.phone.trim()}`,
      city: form.city.trim(),
      state: form.state.trim() || undefined,
      country: form.country.trim(),
    };
    try {
      sessionStorage.setItem("pending_registration_data", JSON.stringify(pendingData));
      await sendOtp({ email, ...pendingData });
      sessionStorage.setItem("register_email", email);
      router.push(`/verify?email=${encodeURIComponent(email)}`);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 409) {
        setAlreadyRegistered(true);
      } else {
        setGlobalError(err instanceof Error ? err.message : "Registration failed");
      }
    } finally {
      setLoading(false);
    }
  };

  const inputClass = (hasError: boolean) =>
    `w-full border rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-indigo-400 dark:bg-gray-700 dark:text-white dark:placeholder-gray-400 ${
      hasError ? "border-red-400" : "border-gray-300 dark:border-gray-600"
    }`;

  return (
    <div>
      <h2 className="text-xl font-semibold mb-2 text-center">Create your account</h2>
      <p className="text-sm text-gray-500 dark:text-gray-400 mb-6 text-center">
        Already have one?{" "}
        <button
          type="button"
          onClick={() => router.push("/login")}
          className="text-indigo-600 hover:underline"
        >
          Sign in
        </button>
      </p>

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Email */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Email address
          </label>
          <input
            type="email"
            value={form.email}
            onChange={setField("email")}
            placeholder="you@example.com"
            className={inputClass(!!errors.email)}
          />
          {errors.email && (
            <p className="text-red-500 text-xs mt-1">{errors.email}</p>
          )}
        </div>

        {/* Phone */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            Phone number
          </label>
          <div className="flex gap-2">
            <select
              value={form.countryCode}
              onChange={setField("countryCode")}
              className="border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-indigo-400 text-sm"
            >
              {COUNTRY_CODES.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.label}
                </option>
              ))}
            </select>
            <input
              type="tel"
              value={form.phone}
              onChange={setField("phone")}
              placeholder="712345678"
              className={`flex-1 border rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-indigo-400 dark:bg-gray-700 dark:text-white dark:placeholder-gray-400 ${
                errors.phone ? "border-red-400" : "border-gray-300 dark:border-gray-600"
              }`}
            />
          </div>
          {errors.phone && (
            <p className="text-red-500 text-xs mt-1">{errors.phone}</p>
          )}
        </div>

        {/* City */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">City</label>
          <input
            type="text"
            value={form.city}
            onChange={setField("city")}
            placeholder="Bucharest"
            className={inputClass(!!errors.city)}
          />
          {errors.city && (
            <p className="text-red-500 text-xs mt-1">{errors.city}</p>
          )}
        </div>

        {/* State (optional) */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">
            State / County{" "}
            <span className="text-gray-400 font-normal">(optional)</span>
          </label>
          <input
            type="text"
            value={form.state}
            onChange={setField("state")}
            placeholder="e.g. Ilfov"
            className="w-full border border-gray-300 dark:border-gray-600 dark:bg-gray-700 dark:text-white dark:placeholder-gray-400 rounded-lg px-4 py-2.5 focus:outline-none focus:ring-2 focus:ring-indigo-400"
          />
        </div>

        {/* Country */}
        <div>
          <label className="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">Country</label>
          <input
            type="text"
            value={form.country}
            onChange={setField("country")}
            placeholder="Romania"
            className={inputClass(!!errors.country)}
          />
          {errors.country && (
            <p className="text-red-500 text-xs mt-1">{errors.country}</p>
          )}
        </div>

        {alreadyRegistered && (
          <p className="text-sm text-center text-amber-700 dark:text-amber-400">
            This email is already registered.{" "}
            <button
              type="button"
              onClick={() => router.push("/login")}
              className="underline font-semibold hover:text-amber-900"
            >
              Log in instead
            </button>
          </p>
        )}

        {globalError && (
          <p className="text-red-500 text-sm text-center">{globalError}</p>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-indigo-600 text-white rounded-lg py-3 font-semibold hover:bg-indigo-700 disabled:opacity-50 flex items-center justify-center gap-2"
        >
          {loading && <Loader2 className="animate-spin w-4 h-4" />}
          Send verification code
        </button>
      </form>
    </div>
  );
}
