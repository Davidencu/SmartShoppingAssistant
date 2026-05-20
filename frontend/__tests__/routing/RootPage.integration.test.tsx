/**
 * Integration tests for app/page.tsx — the root redirect/magic-link handler.
 * This component has no visible UI; its job is purely routing:
 *   - No hash → redirect to /login or /dashboard based on token
 *   - Hash with access_token + recognised type → call verifyMagicLink, go to /register/passkey
 *   - Hash present but unrecognised → fall through to token check
 *   - verifyMagicLink failure → go to /register
 */
import React from "react";
import { render, waitFor } from "@testing-library/react";
import RootPage from "@/app/page";
import * as api from "@/lib/api";

const mockReplace = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace, push: jest.fn() }),
}));
jest.mock("@/lib/api");

const setHash = (hash: string) => {
  window.history.pushState({}, "", hash || "/");
};

describe("RootPage routing", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    setHash("/"); // reset URL to no hash
  });

  afterEach(() => {
    setHash("/");
  });

  // No hash, no token

  it("no hash + no token → replaces to /login", async () => {
    render(<RootPage />);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
  });

  // No hash, token present

  it("no hash + token in localStorage → replaces to /dashboard", async () => {
    localStorage.setItem("smartshop_token", "valid-jwt");
    render(<RootPage />);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("no hash + token present → does NOT call verifyMagicLink", async () => {
    localStorage.setItem("smartshop_token", "valid-jwt");
    render(<RootPage />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalled());
    expect(api.verifyMagicLink).not.toHaveBeenCalled();
  });

  // Hash with type=signup

  it("hash type=signup → calls verifyMagicLink with the access_token", async () => {
    jest.mocked(api.verifyMagicLink).mockResolvedValue({
      user_id: "uid", email: "a@b.com", options: { challenge: "c" },
    });
    setHash("#access_token=TOKEN123&type=signup");
    render(<RootPage />);
    await waitFor(() => {
      expect(api.verifyMagicLink).toHaveBeenCalledWith("TOKEN123");
    });
  });

  it("hash type=signup success → sets sessionStorage passkey_options", async () => {
    const options = { challenge: "abc", rp: { id: "localhost" } };
    jest.mocked(api.verifyMagicLink).mockResolvedValue({
      user_id: "uid", email: "a@b.com", options,
    });
    setHash("#access_token=TOKEN&type=signup");
    render(<RootPage />);
    await waitFor(() => {
      expect(sessionStorage.getItem("passkey_options")).toBe(JSON.stringify(options));
    });
  });

  it("hash type=signup success → sets sessionStorage pending_email", async () => {
    jest.mocked(api.verifyMagicLink).mockResolvedValue({
      user_id: "uid", email: "alice@example.com", options: {},
    });
    setHash("#access_token=TOKEN&type=signup");
    render(<RootPage />);
    await waitFor(() => {
      expect(sessionStorage.getItem("pending_email")).toBe("alice@example.com");
    });
  });

  it("hash type=signup success → replaces to /register/passkey", async () => {
    jest.mocked(api.verifyMagicLink).mockResolvedValue({
      user_id: "uid", email: "a@b.com", options: {},
    });
    setHash("#access_token=TOKEN&type=signup");
    render(<RootPage />);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/register/passkey");
    });
  });

  // Hash with type=magiclink

  it("hash type=magiclink → calls verifyMagicLink and redirects to /register/passkey", async () => {
    jest.mocked(api.verifyMagicLink).mockResolvedValue({
      user_id: "uid", email: "a@b.com", options: {},
    });
    setHash("#access_token=TOKEN&type=magiclink");
    render(<RootPage />);
    await waitFor(() => {
      expect(api.verifyMagicLink).toHaveBeenCalledWith("TOKEN");
      expect(mockReplace).toHaveBeenCalledWith("/register/passkey");
    });
  });

  // Hash with type=email

  it("hash type=email → calls verifyMagicLink and redirects to /register/passkey", async () => {
    jest.mocked(api.verifyMagicLink).mockResolvedValue({
      user_id: "uid", email: "a@b.com", options: {},
    });
    setHash("#access_token=TOKEN&type=email");
    render(<RootPage />);
    await waitFor(() => {
      expect(api.verifyMagicLink).toHaveBeenCalledWith("TOKEN");
      expect(mockReplace).toHaveBeenCalledWith("/register/passkey");
    });
  });

  // Hash with unrecognised type

  it("hash type=recovery → ignores magic link, falls through to token check → /login", async () => {
    setHash("#access_token=TOKEN&type=recovery");
    render(<RootPage />);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
    expect(api.verifyMagicLink).not.toHaveBeenCalled();
  });

  it("hash type=recovery + token in localStorage → redirects to /dashboard, not magic link", async () => {
    localStorage.setItem("smartshop_token", "jwt");
    setHash("#access_token=TOKEN&type=recovery");
    render(<RootPage />);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/dashboard");
    });
    expect(api.verifyMagicLink).not.toHaveBeenCalled();
  });

  // Hash without access_token

  it("hash without access_token → falls through to token check → /login", async () => {
    setHash("#type=signup&foo=bar");
    render(<RootPage />);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
    expect(api.verifyMagicLink).not.toHaveBeenCalled();
  });

  // verifyMagicLink API failure

  it("hash type=signup + API throws → replaces to /register, no sessionStorage written", async () => {
    jest.mocked(api.verifyMagicLink).mockRejectedValue(new Error("Invalid token"));
    setHash("#access_token=BAD&type=signup");
    render(<RootPage />);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/register");
    });
    expect(sessionStorage.getItem("passkey_options")).toBeNull();
    expect(sessionStorage.getItem("pending_email")).toBeNull();
  });

  it("API failure → does NOT redirect to /dashboard or /login", async () => {
    jest.mocked(api.verifyMagicLink).mockRejectedValue(new Error("Expired"));
    setHash("#access_token=BAD&type=signup");
    render(<RootPage />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalled());
    expect(mockReplace).not.toHaveBeenCalledWith("/dashboard");
    expect(mockReplace).not.toHaveBeenCalledWith("/login");
  });

  // magic link takes precedence over existing token

  it("hash type=signup + token in localStorage → still processes magic link (registration wins)", async () => {
    localStorage.setItem("smartshop_token", "existing-jwt");
    jest.mocked(api.verifyMagicLink).mockResolvedValue({
      user_id: "new-uid", email: "new@example.com", options: {},
    });
    setHash("#access_token=NEW_TOKEN&type=signup");
    render(<RootPage />);
    await waitFor(() => {
      expect(api.verifyMagicLink).toHaveBeenCalledWith("NEW_TOKEN");
      expect(mockReplace).toHaveBeenCalledWith("/register/passkey");
    });
    expect(mockReplace).not.toHaveBeenCalledWith("/dashboard");
  });
});
