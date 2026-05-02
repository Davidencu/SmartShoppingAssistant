import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PasskeyEnrollment from "@/components/auth/PasskeyEnrollment";

const mockEnroll = jest.fn();
const mockChallenge = jest.fn();
const mockVerify = jest.fn();
const mockUpdateUser = jest.fn();
const mockRouterReplace = jest.fn();

jest.mock("@/lib/supabase/client", () => ({
  createClient: () => ({
    auth: {
      mfa: {
        enroll: mockEnroll,
        challenge: mockChallenge,
        verify: mockVerify,
      },
      updateUser: mockUpdateUser,
    },
  }),
}));

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockRouterReplace }),
}));

jest.mock("@simplewebauthn/browser", () => ({
  startRegistration: jest.fn(),
  browserSupportsWebAuthn: jest.fn(() => true),
}));

import { startRegistration, browserSupportsWebAuthn } from "@simplewebauthn/browser";

describe("PasskeyEnrollment", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockUpdateUser.mockResolvedValue({ data: {}, error: null });
    (browserSupportsWebAuthn as jest.Mock).mockReturnValue(true);
  });

  it("renders enroll button", () => {
    render(<PasskeyEnrollment />);
    expect(screen.getByRole("button", { name: /create passkey/i })).toBeInTheDocument();
  });

  it("renders skip button", () => {
    render(<PasskeyEnrollment />);
    expect(screen.getByRole("button", { name: /skip/i })).toBeInTheDocument();
  });

  it("skip navigates to dashboard", async () => {
    render(<PasskeyEnrollment />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /skip/i }));
    expect(mockRouterReplace).toHaveBeenCalledWith("/dashboard");
  });

  it("completes passkey enrollment and redirects to wallet", async () => {
    mockEnroll.mockResolvedValue({
      data: {
        id: "factor-1",
        webAuthn: { creationOptions: {} },
      },
      error: null,
    });
    (startRegistration as jest.Mock).mockResolvedValue({ id: "cred-1" });
    mockChallenge.mockResolvedValue({
      data: { id: "challenge-1" },
      error: null,
    });
    mockVerify.mockResolvedValue({ data: {}, error: null });

    render(<PasskeyEnrollment />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /create passkey/i }));

    await waitFor(() => {
      expect(mockUpdateUser).toHaveBeenCalledWith({
        data: { passkey_enrolled: true },
      });
      expect(mockRouterReplace).toHaveBeenCalledWith("/dashboard/wallet");
    });
  });

  it("shows error when browser does not support WebAuthn", async () => {
    (browserSupportsWebAuthn as jest.Mock).mockReturnValue(false);

    render(<PasskeyEnrollment />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /create passkey/i }));

    await waitFor(() => {
      expect(screen.getByText(/does not support passkeys/i)).toBeInTheDocument();
    });
  });

  it("shows user-friendly error when passkey is cancelled (NotAllowedError)", async () => {
    mockEnroll.mockResolvedValue({
      data: { id: "factor-1", webAuthn: { creationOptions: {} } },
      error: null,
    });
    const err = new Error("cancelled");
    err.name = "NotAllowedError";
    (startRegistration as jest.Mock).mockRejectedValue(err);

    render(<PasskeyEnrollment />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: /create passkey/i }));

    await waitFor(() => {
      expect(screen.getByText(/was cancelled/i)).toBeInTheDocument();
    });
  });
});
