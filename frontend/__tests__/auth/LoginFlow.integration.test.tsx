/**
 * Integration tests for the login phase.
 * Each test exercises a complete sequence of user interactions and API responses
 * the same way a real user would experience the flow.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginForm from "@/components/auth/LoginForm";
import * as api from "@/lib/api";
import * as webauthn from "@/lib/webauthn";

const mockPush = jest.fn();
const mockReplace = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
}));
jest.mock("@/lib/api");
jest.mock("@/lib/webauthn");

const fillEmail = async (email: string) =>
  userEvent.type(screen.getByPlaceholderText("you@example.com"), email);

const submitEmail = () =>
  fireEvent.submit(screen.getByRole("button", { name: /continue/i }));

describe("Login flow — sequences", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockPush.mockClear();
    mockReplace.mockClear();
  });

  // -----------------------------------------------------------------------
  // Sequence A – New user: email not found → redirect to /register
  // -----------------------------------------------------------------------
  it("Seq A: unknown email → redirects to /register with email in sessionStorage", async () => {
    jest.mocked(api.checkEmail).mockResolvedValue({ exists: false });
    const setItem = jest.spyOn(Storage.prototype, "setItem");

    render(<LoginForm />);
    await fillEmail("new@example.com");
    submitEmail();

    await waitFor(() => {
      expect(api.checkEmail).toHaveBeenCalledWith("new@example.com");
      expect(setItem).toHaveBeenCalledWith("register_email", "new@example.com");
      expect(mockPush).toHaveBeenCalledWith("/register");
    });

    setItem.mockRestore();
  });

  // -----------------------------------------------------------------------
  // Sequence B – Returning user: full happy path → dashboard
  // -----------------------------------------------------------------------
  it("Seq B: known email → challenge → biometric → token stored → /dashboard", async () => {
    jest.mocked(api.checkEmail).mockResolvedValue({ exists: true });
    jest.mocked(api.getPasskeyChallenge).mockResolvedValue({ options: { rpId: "localhost" } });
    jest.mocked(webauthn.authenticatePasskey).mockResolvedValue({} as never);
    jest.mocked(api.verifyPasskey).mockResolvedValue({ token: "jwt-abc" });
    const setItem = jest.spyOn(Storage.prototype, "setItem");

    render(<LoginForm />);
    await fillEmail("user@example.com");
    submitEmail();

    await waitFor(() => {
      expect(api.checkEmail).toHaveBeenCalledWith("user@example.com");
      expect(api.getPasskeyChallenge).toHaveBeenCalledWith("user@example.com");
      expect(webauthn.authenticatePasskey).toHaveBeenCalled();
      expect(api.verifyPasskey).toHaveBeenCalledWith("user@example.com", {});
      expect(setItem).toHaveBeenCalledWith("smartshop_token", "jwt-abc");
      expect(mockPush).toHaveBeenCalledWith("/dashboard");
    });

    setItem.mockRestore();
  });

  // -----------------------------------------------------------------------
  // Sequence C – Network error during checkEmail → error shown, email step
  // -----------------------------------------------------------------------
  it("Seq C: checkEmail network error → shows error, stays on email form", async () => {
    jest.mocked(api.checkEmail).mockRejectedValue(new Error("Network error"));

    render(<LoginForm />);
    await fillEmail("user@example.com");
    submitEmail();

    await waitFor(() => {
      expect(screen.getByText(/network error/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /continue/i })).toBeInTheDocument();
    });
    expect(mockPush).not.toHaveBeenCalled();
  });

  // -----------------------------------------------------------------------
  // Sequence D – No passkey registered → challenge fails → error, email step
  // -----------------------------------------------------------------------
  it("Seq D: passkey challenge fails (no passkey registered) → shows error", async () => {
    jest.mocked(api.checkEmail).mockResolvedValue({ exists: true });
    jest.mocked(api.getPasskeyChallenge).mockRejectedValue(
      new Error("No passkey registered for this user")
    );

    render(<LoginForm />);
    await fillEmail("user@example.com");
    submitEmail();

    await waitFor(() => {
      expect(screen.getByText(/no passkey registered/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /continue/i })).toBeInTheDocument();
    });
    expect(mockPush).not.toHaveBeenCalled();
  });

  // -----------------------------------------------------------------------
  // Sequence E – User cancels biometric → error shown, back to email step
  // -----------------------------------------------------------------------
  it("Seq E: user cancels biometric prompt → shows error, back to email form", async () => {
    jest.mocked(api.checkEmail).mockResolvedValue({ exists: true });
    jest.mocked(api.getPasskeyChallenge).mockResolvedValue({ options: {} });
    jest.mocked(webauthn.authenticatePasskey).mockRejectedValue(
      new Error("User cancelled the operation")
    );

    render(<LoginForm />);
    await fillEmail("user@example.com");
    submitEmail();

    await waitFor(() => {
      expect(screen.getByText(/user cancelled/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /continue/i })).toBeInTheDocument();
    });
    expect(mockPush).not.toHaveBeenCalled();
  });

  // -----------------------------------------------------------------------
  // Sequence F – Credential rejected by server → error, back to email step
  // -----------------------------------------------------------------------
  it("Seq F: server rejects credential → shows error, back to email form", async () => {
    jest.mocked(api.checkEmail).mockResolvedValue({ exists: true });
    jest.mocked(api.getPasskeyChallenge).mockResolvedValue({ options: {} });
    jest.mocked(webauthn.authenticatePasskey).mockResolvedValue({} as never);
    jest.mocked(api.verifyPasskey).mockRejectedValue(
      new Error("Passkey verification failed: invalid signature")
    );

    render(<LoginForm />);
    await fillEmail("user@example.com");
    submitEmail();

    await waitFor(() => {
      expect(screen.getByText(/passkey verification failed/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /continue/i })).toBeInTheDocument();
    });
    expect(mockPush).not.toHaveBeenCalled();
  });

  // -----------------------------------------------------------------------
  // Sequence G – First attempt fails, user retries and succeeds
  // -----------------------------------------------------------------------
  it("Seq G: first biometric fails, user resubmits, second attempt succeeds → /dashboard", async () => {
    // First attempt: biometric fails
    jest.mocked(api.checkEmail).mockResolvedValue({ exists: true });
    jest.mocked(api.getPasskeyChallenge).mockResolvedValue({ options: {} });
    jest.mocked(webauthn.authenticatePasskey).mockRejectedValueOnce(
      new Error("Authentication failed")
    );

    render(<LoginForm />);
    await fillEmail("user@example.com");
    submitEmail();

    await waitFor(() => {
      expect(screen.getByText(/authentication failed/i)).toBeInTheDocument();
    });

    // Second attempt: succeeds
    jest.mocked(webauthn.authenticatePasskey).mockResolvedValue({} as never);
    jest.mocked(api.verifyPasskey).mockResolvedValue({ token: "jwt-retry" });
    const setItem = jest.spyOn(Storage.prototype, "setItem");

    submitEmail();

    await waitFor(() => {
      expect(setItem).toHaveBeenCalledWith("smartshop_token", "jwt-retry");
      expect(mockPush).toHaveBeenCalledWith("/dashboard");
    });

    setItem.mockRestore();
  });

  // -----------------------------------------------------------------------
  // Sequence H – Empty email validation prevents API calls
  // -----------------------------------------------------------------------
  it("Seq H: empty submit never calls checkEmail", async () => {
    render(<LoginForm />);
    submitEmail();

    await waitFor(() => {
      expect(screen.getByText(/email is required/i)).toBeInTheDocument();
    });
    expect(api.checkEmail).not.toHaveBeenCalled();
  });

  // -----------------------------------------------------------------------
  // Sequence I – Invalid email format validation prevents API calls
  // -----------------------------------------------------------------------
  it("Seq I: malformed email never calls checkEmail", async () => {
    render(<LoginForm />);
    await fillEmail("notanemail");
    submitEmail();

    await waitFor(() => {
      expect(screen.getByText(/valid email/i)).toBeInTheDocument();
    });
    expect(api.checkEmail).not.toHaveBeenCalled();
  });
});
