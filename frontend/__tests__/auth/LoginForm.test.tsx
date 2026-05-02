import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginForm from "@/components/auth/LoginForm";

const mockSignInWithOtp = jest.fn();
const mockListFactors = jest.fn();
const mockChallenge = jest.fn();
const mockVerify = jest.fn();
const mockRouterReplace = jest.fn();

jest.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: {
      signInWithOtp: mockSignInWithOtp,
      mfa: {
        listFactors: mockListFactors,
        challenge: mockChallenge,
        verify: mockVerify,
      },
    },
  }),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockRouterReplace }),
}));

jest.mock("@simplewebauthn/browser", () => ({
  browserSupportsWebAuthn: jest.fn(() => false),
  startAuthentication: jest.fn(),
}));

import { browserSupportsWebAuthn, startAuthentication } from "@simplewebauthn/browser";

describe("LoginForm", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockListFactors.mockResolvedValue({ data: { webauthn: [] }, error: null });
    mockSignInWithOtp.mockResolvedValue({ data: {}, error: null });
    (browserSupportsWebAuthn as jest.Mock).mockReturnValue(false);
  });

  it("renders email input and continue button", () => {
    render(<LoginForm />);
    expect(screen.getByPlaceholderText("you@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /continue/i })).toBeInTheDocument();
  });

  it("shows register link", () => {
    render(<LoginForm />);
    expect(screen.getByRole("link", { name: /create one/i })).toBeInTheDocument();
  });

  it("shows OTP-sent state after submitting email (no passkey)", async () => {
    render(<LoginForm />);
    const user = userEvent.setup();

    await user.type(screen.getByPlaceholderText("you@example.com"), "test@example.com");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(screen.getByText(/check your inbox/i)).toBeInTheDocument();
    });
    expect(mockSignInWithOtp).toHaveBeenCalledWith(
      expect.objectContaining({ email: "test@example.com" })
    );
  });

  it("does not submit with empty email", async () => {
    render(<LoginForm />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /continue/i }));
    expect(mockSignInWithOtp).not.toHaveBeenCalled();
    expect(mockListFactors).not.toHaveBeenCalled();
  });

  it("shows error message when signInWithOtp fails", async () => {
    mockSignInWithOtp.mockResolvedValue({
      data: {},
      error: new Error("Email not allowed"),
    });

    render(<LoginForm />);
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("you@example.com"), "bad@example.com");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(screen.getByText(/email not allowed/i)).toBeInTheDocument();
    });
  });

  it("triggers passkey flow when passkey is enrolled and browser supports it", async () => {
    (browserSupportsWebAuthn as jest.Mock).mockReturnValue(true);
    mockListFactors.mockResolvedValue({
      data: { webauthn: [{ id: "factor-1" }] },
      error: null,
    });
    mockChallenge.mockResolvedValue({
      data: {
        id: "challenge-1",
        webAuthn: { requestOptions: {} },
      },
      error: null,
    });
    (startAuthentication as jest.Mock).mockResolvedValue({ id: "cred-1" });
    mockVerify.mockResolvedValue({ data: {}, error: null });

    render(<LoginForm />);
    const user = userEvent.setup();
    await user.type(screen.getByPlaceholderText("you@example.com"), "user@example.com");
    await user.click(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => expect(mockRouterReplace).toHaveBeenCalledWith("/dashboard"));
  });
});
