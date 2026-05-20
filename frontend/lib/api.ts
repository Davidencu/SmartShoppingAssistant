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

// Search / Chat

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  image_base64?: string;
}

export interface ProductScores {
  cost_efficiency: number;
  quality_confidence: number;
  logistics: number;
  trust: number;
}

export interface Product {
  rank: number;
  title: string;
  url: string;
  price: number | null;
  currency: string | null;
  image_url: string | null;
  scores: ProductScores;
  value_score: number;
  reasoning: string;
}

export interface IntentParams {
  category: string | null;
  budget: string | null;
  budget_max: number | null;
  budget_currency: string | null;
  preference: string | null;
}

export interface ChatResponse {
  intent: "CHAT" | "CLARIFY" | "SEARCH";
  reply: string | null;
  products: Product[] | null;
  collected_params: IntentParams;
  from_cache: boolean;
  fallback_message: string | null;
}

export interface HistoryEntry {
  id: string;
  prompt: string;
  intent: "CHAT" | "CLARIFY" | "SEARCH";
  image_included: boolean;
  response_json: ChatResponse;
  created_at: string;
}

export function getHistory(token: string) {
  return request<{ entries: HistoryEntry[] }>("/search/history", {}, token);
}

export function sendChatMessage(
  messages: ChatMessage[],
  token: string,
  excludedUrls?: string[],
) {
  return request<ChatResponse>(
    "/search/chat",
    {
      method: "POST",
      body: JSON.stringify({
        messages,
        ...(excludedUrls && excludedUrls.length > 0 ? { excluded_urls: excludedUrls } : {}),
      }),
    },
    token
  );
}
