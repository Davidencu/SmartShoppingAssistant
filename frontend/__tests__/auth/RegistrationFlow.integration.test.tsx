/**
 * Integration tests for the full new-user registration flow:
 *   RegisterForm → (magic link) → PasskeyEnrollment → PlanSelection → /dashboard
 *
 * Each sequence tests the state handoff between pages — sessionStorage,
 * localStorage, and navigation — the same way a real user traverses them.
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RegisterForm from "@/components/auth/RegisterForm";
import PasskeyEnrollment from "@/components/auth/PasskeyEnrollment";
import PlanSelection from "@/components/plan/PlanSelection";
import * as api from "@/lib/api";
import * as webauthn from "@/lib/webauthn";

const mockPush = jest.fn();
const mockReplace = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
}));
jest.mock("@/lib/api", () => {
  const { ApiError } = jest.requireActual("@/lib/api");
  return {
    ApiError,
    sendOtp: jest.fn(),
    registerPasskey: jest.fn(),
    selectFreePlan: jest.fn(),
    createProCheckout: jest.fn(),
    checkEmail: jest.fn(),
    getPasskeyChallenge: jest.fn(),
    verifyPasskey: jest.fn(),
    verifyMagicLink: jest.fn(),
    getPlanStatus: jest.fn(),
  };
});
jest.mock("@/lib/webauthn");

const originalLocation = window.location;
beforeAll(() => {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { ...originalLocation, href: "" },
  });
});
afterAll(() => {
  Object.defineProperty(window, "location", {
    configurable: true,
    value: originalLocation,
  });
});

const fillRegisterForm = async () => {
  await userEvent.type(screen.getByPlaceholderText("you@example.com"), "alice@example.com");
  await userEvent.type(screen.getByPlaceholderText("712345678"), "712345678");
  await userEvent.type(screen.getByPlaceholderText("123 Main St"), "10 Main St");
  await userEvent.type(screen.getByPlaceholderText("Bucharest"), "Bucharest");
  await userEvent.type(screen.getByPlaceholderText("010101"), "010101");
  await userEvent.type(screen.getByPlaceholderText("Romania"), "Romania");
};

describe("Registration flow — sequences", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();
    mockPush.mockClear();
    mockReplace.mockClear();
  });

  // ── Seq A: RegisterForm → OTP sent → navigate to /verify ─────────────────

  it("Seq A: valid form submission calls sendOtp with correct data", async () => {
    jest.mocked(api.sendOtp).mockResolvedValue({ message: "OTP sent" });
    render(<RegisterForm />);
    await fillRegisterForm();
    fireEvent.click(screen.getByRole("button", { name: /send verification code/i }));
    await waitFor(() => {
      expect(api.sendOtp).toHaveBeenCalledWith(
        expect.objectContaining({
          email: "alice@example.com",
          phone: "+40712345678",
          street_address: "10 Main St",
          city: "Bucharest",
          postal_code: "010101",
          country: "Romania",
        })
      );
    });
  });

  it("Seq A: sendOtp success → stores register_email in sessionStorage", async () => {
    jest.mocked(api.sendOtp).mockResolvedValue({ message: "OTP sent" });
    render(<RegisterForm />);
    await fillRegisterForm();
    fireEvent.click(screen.getByRole("button", { name: /send verification code/i }));
    await waitFor(() => {
      expect(sessionStorage.getItem("register_email")).toBe("alice@example.com");
    });
  });

  it("Seq A: sendOtp success → navigates to /verify with email param", async () => {
    jest.mocked(api.sendOtp).mockResolvedValue({ message: "OTP sent" });
    render(<RegisterForm />);
    await fillRegisterForm();
    fireEvent.click(screen.getByRole("button", { name: /send verification code/i }));
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith(
        expect.stringContaining("/verify")
      );
      expect(mockPush).toHaveBeenCalledWith(
        expect.stringContaining("alice%40example.com")
      );
    });
  });

  it("Seq A: sendOtp success → stores pending_registration_data in sessionStorage", async () => {
    jest.mocked(api.sendOtp).mockResolvedValue({ message: "OTP sent" });
    render(<RegisterForm />);
    await fillRegisterForm();
    fireEvent.click(screen.getByRole("button", { name: /send verification code/i }));
    await waitFor(() => {
      const raw = sessionStorage.getItem("pending_registration_data");
      expect(raw).not.toBeNull();
      const data = JSON.parse(raw!);
      expect(data.phone).toBe("+40712345678");
      expect(data.city).toBe("Bucharest");
    });
  });

  // ── Seq B: Email already registered → 409 UX ─────────────────────────────

  it("Seq B: sendOtp 409 → shows 'already registered' message", async () => {
    const { ApiError } = jest.requireActual("@/lib/api");
    jest.mocked(api.sendOtp).mockRejectedValue(new ApiError("Email already registered", 409));
    render(<RegisterForm />);
    await fillRegisterForm();
    fireEvent.click(screen.getByRole("button", { name: /send verification code/i }));
    await waitFor(() => {
      expect(screen.getByText(/already registered/i)).toBeInTheDocument();
    });
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("Seq B: 409 → shows 'Log in instead' link", async () => {
    const { ApiError } = jest.requireActual("@/lib/api");
    jest.mocked(api.sendOtp).mockRejectedValue(new ApiError("Email already registered", 409));
    render(<RegisterForm />);
    await fillRegisterForm();
    fireEvent.click(screen.getByRole("button", { name: /send verification code/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /log in instead/i })).toBeInTheDocument();
    });
  });

  it("Seq B: 'Log in instead' click → pushes to /login", async () => {
    const { ApiError } = jest.requireActual("@/lib/api");
    jest.mocked(api.sendOtp).mockRejectedValue(new ApiError("Email already registered", 409));
    render(<RegisterForm />);
    await fillRegisterForm();
    fireEvent.click(screen.getByRole("button", { name: /send verification code/i }));
    await waitFor(() => screen.getByRole("button", { name: /log in instead/i }));
    fireEvent.click(screen.getByRole("button", { name: /log in instead/i }));
    expect(mockPush).toHaveBeenCalledWith("/login");
  });

  it("Seq B: non-409 error → shows generic error, no 'Log in instead'", async () => {
    jest.mocked(api.sendOtp).mockRejectedValue(new Error("Network error"));
    render(<RegisterForm />);
    await fillRegisterForm();
    fireEvent.click(screen.getByRole("button", { name: /send verification code/i }));
    await waitFor(() => {
      expect(screen.getByText(/network error/i)).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /log in instead/i })).not.toBeInTheDocument();
    });
  });

  it("Seq B: 'already registered' clears when user changes email field", async () => {
    const { ApiError } = jest.requireActual("@/lib/api");
    jest.mocked(api.sendOtp).mockRejectedValue(new ApiError("Email already registered", 409));
    render(<RegisterForm />);
    await fillRegisterForm();
    fireEvent.click(screen.getByRole("button", { name: /send verification code/i }));
    await waitFor(() => screen.getByText(/already registered/i));
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "x");
    await waitFor(() => {
      expect(screen.queryByText(/already registered/i)).not.toBeInTheDocument();
    });
  });

  // ── Seq C: Validation prevents submission ─────────────────────────────────

  it("Seq C: empty form → shows validation errors, no API call", async () => {
    render(<RegisterForm />);
    fireEvent.click(screen.getByRole("button", { name: /send verification code/i }));
    await waitFor(() => {
      expect(screen.getByText(/valid email/i)).toBeInTheDocument();
    });
    expect(api.sendOtp).not.toHaveBeenCalled();
  });

  it("Seq C: missing city only → shows city required error", async () => {
    render(<RegisterForm />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "a@b.com");
    await userEvent.type(screen.getByPlaceholderText("712345678"), "712345678");
    await userEvent.type(screen.getByPlaceholderText("123 Main St"), "10 St");
    await userEvent.type(screen.getByPlaceholderText("010101"), "010101");
    await userEvent.type(screen.getByPlaceholderText("Romania"), "Romania");
    fireEvent.click(screen.getByRole("button", { name: /send verification code/i }));
    await waitFor(() => {
      expect(screen.getByText(/city is required/i)).toBeInTheDocument();
    });
    expect(api.sendOtp).not.toHaveBeenCalled();
  });

  // ── Seq D: PasskeyEnrollment reads sessionStorage ──────────────────────────

  it("Seq D: PasskeyEnrollment shows both biometric buttons when session data present", () => {
    sessionStorage.setItem("pending_email", "alice@example.com");
    sessionStorage.setItem("passkey_options", JSON.stringify({ challenge: "abc" }));
    render(<PasskeyEnrollment />);
    expect(screen.getByRole("button", { name: /set up with face id/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /set up with touch id/i })).toBeInTheDocument();
  });

  it("Seq D: PasskeyEnrollment with no pending_email → replaces to /login", async () => {
    sessionStorage.removeItem("pending_email");
    render(<PasskeyEnrollment />);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
  });

  // ── Seq E: Face ID enrollment happy path → /plan ──────────────────────────

  it("Seq E: Face ID success → stores token in localStorage", async () => {
    sessionStorage.setItem("pending_email", "alice@example.com");
    sessionStorage.setItem("passkey_options", JSON.stringify({ challenge: "abc" }));
    jest.mocked(webauthn.enrollPasskey).mockResolvedValue({} as never);
    jest.mocked(api.registerPasskey).mockResolvedValue({ token: "jwt-abc" });
    const setItem = jest.spyOn(Storage.prototype, "setItem");

    render(<PasskeyEnrollment />);
    fireEvent.click(screen.getByRole("button", { name: /set up with face id/i }));

    await waitFor(() => {
      expect(setItem).toHaveBeenCalledWith("smartshop_token", "jwt-abc");
    });
    setItem.mockRestore();
  });

  it("Seq E: Face ID success → redirects to /plan", async () => {
    sessionStorage.setItem("pending_email", "alice@example.com");
    sessionStorage.setItem("passkey_options", JSON.stringify({ challenge: "abc" }));
    jest.mocked(webauthn.enrollPasskey).mockResolvedValue({} as never);
    jest.mocked(api.registerPasskey).mockResolvedValue({ token: "jwt-abc" });

    render(<PasskeyEnrollment />);
    fireEvent.click(screen.getByRole("button", { name: /set up with face id/i }));

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/plan");
    });
  });

  it("Seq E: Face ID success → clears passkey_options and pending_email from sessionStorage", async () => {
    sessionStorage.setItem("pending_email", "alice@example.com");
    sessionStorage.setItem("passkey_options", JSON.stringify({ challenge: "abc" }));
    jest.mocked(webauthn.enrollPasskey).mockResolvedValue({} as never);
    jest.mocked(api.registerPasskey).mockResolvedValue({ token: "jwt-abc" });

    render(<PasskeyEnrollment />);
    fireEvent.click(screen.getByRole("button", { name: /set up with face id/i }));

    await waitFor(() => expect(mockPush).toHaveBeenCalledWith("/plan"));
    expect(sessionStorage.getItem("passkey_options")).toBeNull();
    expect(sessionStorage.getItem("pending_email")).toBeNull();
  });

  // ── Seq F: Touch ID enrollment happy path → /plan ─────────────────────────

  it("Seq F: Touch ID success → stores token and redirects to /plan", async () => {
    sessionStorage.setItem("pending_email", "alice@example.com");
    sessionStorage.setItem("passkey_options", JSON.stringify({ challenge: "abc" }));
    jest.mocked(webauthn.enrollPasskey).mockResolvedValue({} as never);
    jest.mocked(api.registerPasskey).mockResolvedValue({ token: "jwt-touch" });
    const setItem = jest.spyOn(Storage.prototype, "setItem");

    render(<PasskeyEnrollment />);
    fireEvent.click(screen.getByRole("button", { name: /set up with touch id/i }));

    await waitFor(() => {
      expect(setItem).toHaveBeenCalledWith("smartshop_token", "jwt-touch");
      expect(mockPush).toHaveBeenCalledWith("/plan");
    });
    setItem.mockRestore();
  });

  // ── Seq G: Enrollment failure → retry → success ───────────────────────────

  it("Seq G: Face ID fails → shows error, buttons re-enabled", async () => {
    sessionStorage.setItem("pending_email", "alice@example.com");
    sessionStorage.setItem("passkey_options", JSON.stringify({ challenge: "abc" }));
    jest.mocked(webauthn.enrollPasskey).mockRejectedValue(new Error("User cancelled"));

    render(<PasskeyEnrollment />);
    fireEvent.click(screen.getByRole("button", { name: /set up with face id/i }));

    await waitFor(() => {
      expect(screen.getByText(/user cancelled/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /set up with face id/i })).not.toBeDisabled();
      expect(screen.getByRole("button", { name: /set up with touch id/i })).not.toBeDisabled();
    });
    expect(mockPush).not.toHaveBeenCalled();
  });

  it("Seq G: after failure, retry with Face ID succeeds → /plan", async () => {
    sessionStorage.setItem("pending_email", "alice@example.com");
    sessionStorage.setItem("passkey_options", JSON.stringify({ challenge: "abc" }));
    jest.mocked(webauthn.enrollPasskey)
      .mockRejectedValueOnce(new Error("Hardware error"))
      .mockResolvedValue({} as never);
    jest.mocked(api.registerPasskey).mockResolvedValue({ token: "jwt-retry" });

    render(<PasskeyEnrollment />);
    fireEvent.click(screen.getByRole("button", { name: /set up with face id/i }));
    await waitFor(() => screen.getByText(/hardware error/i));

    fireEvent.click(screen.getByRole("button", { name: /set up with face id/i }));
    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith("/plan");
    });
  });

  it("Seq G: registerPasskey API failure → shows error, stays on enrollment page", async () => {
    sessionStorage.setItem("pending_email", "alice@example.com");
    sessionStorage.setItem("passkey_options", JSON.stringify({ challenge: "abc" }));
    jest.mocked(webauthn.enrollPasskey).mockResolvedValue({} as never);
    jest.mocked(api.registerPasskey).mockRejectedValue(new Error("Server error"));

    render(<PasskeyEnrollment />);
    fireEvent.click(screen.getByRole("button", { name: /set up with face id/i }));

    await waitFor(() => {
      expect(screen.getByText(/server error/i)).toBeInTheDocument();
    });
    expect(mockPush).not.toHaveBeenCalled();
  });

  // ── Seq H: PlanSelection reads localStorage token ─────────────────────────

  it("Seq H: PlanSelection with no token → still renders buttons (calls API with empty string)", async () => {
    localStorage.removeItem("smartshop_token");
    jest.mocked(api.selectFreePlan).mockRejectedValue(new Error("Unauthorized"));
    render(<PlanSelection />);
    fireEvent.click(screen.getByRole("button", { name: /get started free/i }));
    await waitFor(() => {
      expect(api.selectFreePlan).toHaveBeenCalledWith("");
    });
  });

  it("Seq H: PlanSelection free → API 401 → shows error", async () => {
    localStorage.setItem("smartshop_token", "jwt");
    jest.mocked(api.selectFreePlan).mockRejectedValue(new Error("Unauthorized"));
    render(<PlanSelection />);
    fireEvent.click(screen.getByRole("button", { name: /get started free/i }));
    await waitFor(() => {
      expect(screen.getByText(/unauthorized/i)).toBeInTheDocument();
    });
  });

  // ── Seq I: Full component chain: enroll → free plan → /dashboard ──────────

  it("Seq I: full chain — enroll (Face ID) → selectFreePlan → /dashboard", async () => {
    // Step 1: PasskeyEnrollment
    sessionStorage.setItem("pending_email", "alice@example.com");
    sessionStorage.setItem("passkey_options", JSON.stringify({ challenge: "abc" }));
    jest.mocked(webauthn.enrollPasskey).mockResolvedValue({} as never);
    jest.mocked(api.registerPasskey).mockResolvedValue({ token: "chain-jwt" });

    const { unmount } = render(<PasskeyEnrollment />);
    fireEvent.click(screen.getByRole("button", { name: /set up with face id/i }));
    await waitFor(() => {
      expect(localStorage.getItem("smartshop_token")).toBe("chain-jwt");
      expect(mockPush).toHaveBeenCalledWith("/plan");
    });
    unmount();

    // Step 2: PlanSelection (user navigated to /plan)
    jest.mocked(api.selectFreePlan).mockResolvedValue({ plan: "free", checkout_credits: 2 });
    render(<PlanSelection />);
    fireEvent.click(screen.getByRole("button", { name: /get started free/i }));
    await waitFor(() => {
      expect(api.selectFreePlan).toHaveBeenCalledWith("chain-jwt");
      expect(mockPush).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("Seq I: full chain — enroll (Touch ID) → pro checkout → external redirect", async () => {
    // Step 1: PasskeyEnrollment
    sessionStorage.setItem("pending_email", "alice@example.com");
    sessionStorage.setItem("passkey_options", JSON.stringify({ challenge: "abc" }));
    jest.mocked(webauthn.enrollPasskey).mockResolvedValue({} as never);
    jest.mocked(api.registerPasskey).mockResolvedValue({ token: "pro-jwt" });

    const { unmount } = render(<PasskeyEnrollment />);
    fireEvent.click(screen.getByRole("button", { name: /set up with touch id/i }));
    await waitFor(() => {
      expect(localStorage.getItem("smartshop_token")).toBe("pro-jwt");
    });
    unmount();

    // Step 2: PlanSelection → Pro
    jest.mocked(api.createProCheckout).mockResolvedValue({
      checkout_url: "https://checkout.lemonsqueezy.com/buy/pro",
    });
    render(<PlanSelection />);
    fireEvent.click(screen.getByRole("button", { name: /upgrade to pro/i }));
    await waitFor(() => {
      expect(api.createProCheckout).toHaveBeenCalledWith("pro-jwt");
      expect(window.location.href).toBe("https://checkout.lemonsqueezy.com/buy/pro");
    });
  });
});
