"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, AlertCircle } from "lucide-react";
import { createClient } from "@/lib/supabase/client";
import Link from "next/link";

interface FormState {
  full_name: string;
  email: string;
  phone: string;
  recipient_name: string;
  street: string;
  city: string;
  state: string;
  country: string;
  zip_code: string;
}

const EMPTY: FormState = {
  full_name: "",
  email: "",
  phone: "",
  recipient_name: "",
  street: "",
  city: "",
  state: "",
  country: "RO",
  zip_code: "",
};

export default function RegisterForm() {
  const router = useRouter();
  const [form, setForm] = useState<FormState>(EMPTY);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const supabase = createClient();

  function field(key: keyof FormState) {
    return {
      value: form[key],
      onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
        setForm((prev) => ({ ...prev, [key]: e.target.value })),
    };
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const { error: otpError } = await supabase.auth.signInWithOtp({
        email: form.email,
        options: {
          shouldCreateUser: true,
          emailRedirectTo: `${window.location.origin}/auth/callback?next=/register/passkey`,
          data: {
            full_name: form.full_name,
            phone: form.phone,
            pending_address: {
              recipient_name: form.recipient_name || form.full_name,
              street: form.street,
              city: form.city,
              state: form.state || null,
              country: form.country,
              zip_code: form.zip_code,
            },
          },
        },
      });

      if (otpError) throw otpError;

      router.push(`/verify?email=${encodeURIComponent(form.email)}`);
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : "Registration failed. Please check your details and try again."
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-8 shadow-sm space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Create account</h2>
        <p className="mt-1 text-sm text-slate-500">
          You'll verify your email, then set up a passkey for fast, secure sign-in.
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-5" noValidate>
        <Section label="Personal details">
          <Field label="Full name" required>
            <input
              type="text"
              required
              minLength={2}
              placeholder="Ion Popescu"
              {...field("full_name")}
              className={inputCls}
            />
          </Field>
          <Field label="Email address" required>
            <input
              type="email"
              required
              placeholder="ion@example.com"
              {...field("email")}
              className={inputCls}
            />
          </Field>
          <Field label="Phone number" required>
            <input
              type="tel"
              required
              placeholder="+40712345678"
              {...field("phone")}
              className={inputCls}
            />
          </Field>
        </Section>

        <Section label="Shipping address">
          <Field label="Recipient name" required>
            <input
              type="text"
              required
              placeholder="Name on parcel"
              {...field("recipient_name")}
              className={inputCls}
            />
          </Field>
          <Field label="Street" required>
            <input
              type="text"
              required
              placeholder="Strada Victoriei 1"
              {...field("street")}
              className={inputCls}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="City" required>
              <input
                type="text"
                required
                placeholder="București"
                {...field("city")}
                className={inputCls}
              />
            </Field>
            <Field label="ZIP code" required>
              <input
                type="text"
                required
                placeholder="010011"
                {...field("zip_code")}
                className={inputCls}
              />
            </Field>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <Field label="State / County">
              <input
                type="text"
                placeholder="Ilfov"
                {...field("state")}
                className={inputCls}
              />
            </Field>
            <Field label="Country" required>
              <input
                type="text"
                required
                placeholder="RO"
                maxLength={3}
                {...field("country")}
                className={inputCls}
              />
            </Field>
          </div>
        </Section>

        <button
          type="submit"
          disabled={loading}
          className="flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-indigo-700 disabled:opacity-60"
        >
          {loading && <Loader2 className="h-4 w-4 animate-spin" />}
          {loading ? "Sending verification…" : "Create account"}
        </button>
      </form>

      <p className="text-center text-sm text-slate-500">
        Already have an account?{" "}
        <Link href="/login" className="text-indigo-600 hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}

const inputCls =
  "w-full rounded-lg border border-slate-300 px-3 py-2.5 text-sm focus:border-indigo-500 focus:outline-none focus:ring-1 focus:ring-indigo-500";

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <fieldset className="space-y-3">
      <legend className="text-xs font-semibold uppercase tracking-wide text-slate-400">
        {label}
      </legend>
      {children}
    </fieldset>
  );
}

function Field({
  label,
  required,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-slate-700">
        {label}
        {required && <span className="ml-0.5 text-red-500">*</span>}
      </label>
      {children}
    </div>
  );
}
