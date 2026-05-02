import type { ProfileCreate, ProfileResponse, WalletResponse } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(
  path: string,
  token: string,
  init?: RequestInit
): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
      ...init?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail ?? `API error ${res.status}`);
  }

  return res.json() as Promise<T>;
}

export async function createProfile(
  token: string,
  data: ProfileCreate
): Promise<ProfileResponse> {
  return apiFetch<ProfileResponse>("/auth/profile", token, {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export async function profileExists(token: string): Promise<boolean> {
  const data = await apiFetch<{ exists: boolean }>(
    "/auth/profile/exists",
    token
  );
  return data.exists;
}

export async function getWallet(token: string): Promise<WalletResponse> {
  return apiFetch<WalletResponse>("/wallet", token);
}
