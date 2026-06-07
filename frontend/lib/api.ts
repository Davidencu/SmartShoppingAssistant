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

export async function sendChatMessage(
  messages: ChatMessage[],
  token: string,
  excludedUrls?: string[],
  onStatus?: (message: string) => void,
): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/search/chat`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({
      messages,
      ...(excludedUrls && excludedUrls.length > 0 ? { excluded_urls: excludedUrls } : {}),
    }),
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(
      (body as { detail?: string }).detail ?? `Request failed: ${res.status}`,
      res.status
    );
  }

  // The backend streams SSE events: `data: {...}\n\n`
  // We read the stream line-by-line and react to each event type.
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Process every complete line in the accumulated buffer.
    let newlineIdx: number;
    while ((newlineIdx = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, newlineIdx).trimEnd();
      buffer = buffer.slice(newlineIdx + 1);

      if (!line.startsWith("data: ")) continue;

      const event = JSON.parse(line.slice(6)) as {
        type: "status" | "result" | "error";
        message?: string;
        data?: ChatResponse;
      };

      if (event.type === "status") {
        onStatus?.(event.message ?? "");
      } else if (event.type === "result" && event.data) {
        reader.cancel();
        return event.data;
      } else if (event.type === "error") {
        throw new ApiError(event.message ?? "Pipeline error", 500);
      }
    }
  }

  throw new ApiError("Stream ended without a result", 500);
}
