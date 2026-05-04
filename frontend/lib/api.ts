const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  token?: string
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(
      (body as { detail?: string }).detail ?? `Request failed: ${res.status}`,
      res.status
    );
  }
  return res.json() as Promise<T>;
}

export function checkEmail(email: string) {
  return request<{ exists: boolean }>("/auth/check-email", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export interface RegistrationData {
  email: string;
  phone: string;
  street_address: string;
  city: string;
  state?: string;
  postal_code: string;
  country: string;
}

export function sendOtp(data: RegistrationData) {
  return request<{ message: string }>("/auth/send-otp", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function verifyOtp(email: string, otp: string) {
  return request<{ user_id: string; options: object }>("/auth/verify-otp", {
    method: "POST",
    body: JSON.stringify({ email, otp }),
  });
}

export function registerPasskey(email: string, credential: object) {
  return request<{ token: string }>("/auth/passkey/register", {
    method: "POST",
    body: JSON.stringify({ email, credential }),
  });
}

export function getPasskeyChallenge(email: string) {
  return request<{ options: object }>("/auth/passkey/challenge", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

export function verifyPasskey(email: string, credential: object) {
  return request<{ token: string }>("/auth/passkey/verify", {
    method: "POST",
    body: JSON.stringify({ email, credential }),
  });
}

export function verifyMagicLink(accessToken: string) {
  return request<{ user_id: string; email: string; options: object }>("/auth/verify-magic", {
    method: "POST",
    body: JSON.stringify({ access_token: accessToken }),
  });
}

export function getPlanStatus(token: string) {
  return request<{ plan: string; checkout_credits: number }>("/plan/status", {}, token);
}

export function selectFreePlan(token: string) {
  return request<{ plan: string; checkout_credits: number }>(
    "/plan/select",
    { method: "POST", body: JSON.stringify({ plan: "free" }) },
    token
  );
}

export function createProCheckout(token: string) {
  return request<{ checkout_url: string }>("/plan/checkout", { method: "POST" }, token);
}
