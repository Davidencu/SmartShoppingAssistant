import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import PasskeyEnrollment from "@/components/auth/PasskeyEnrollment";
import * as api from "@/lib/api";
import * as webauthn from "@/lib/webauthn";

const mockPush = jest.fn();
const mockReplace = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
}));
jest.mock("@/lib/api");
jest.mock("@/lib/webauthn");

const mockSessionStorage = {
  getItem: jest.fn((key: string) => {
    if (key === "pending_email") return "test@example.com";
    if (key === "passkey_options") return JSON.stringify({ challenge: "abc123" });
    return null;
  }),
  setItem: jest.fn(),
  removeItem: jest.fn(),
};

Object.defineProperty(window, "sessionStorage", {
  value: mockSessionStorage,
  writable: true,
});

describe("PasskeyEnrollment", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockPush.mockClear();
    mockReplace.mockClear();
    mockSessionStorage.getItem.mockImplementation((key: string) => {
      if (key === "pending_email") return "test@example.com";
      if (key === "passkey_options") return JSON.stringify({ challenge: "abc123" });
      return null;
    });
  });

  it("renders both Face ID and Touch ID buttons", () => {
    render(<PasskeyEnrollment />);
    expect(screen.getByRole("button", { name: /set up with face id/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /set up with touch id/i })).toBeInTheDocument();
  });

  it("shows instructions to choose a biometric method", () => {
    render(<PasskeyEnrollment />);
    expect(screen.getByText(/choose how you want to secure/i)).toBeInTheDocument();
  });

  it("Face ID button: enrolls passkey, stores token, and redirects to /wallet", async () => {
    jest.mocked(webauthn.enrollPasskey).mockResolvedValue({} as never);
    jest.mocked(api.registerPasskey).mockResolvedValue({ token: "test-jwt" });

    const mockSetItem = jest.spyOn(Storage.prototype, "setItem");

    render(<PasskeyEnrollment />);
    fireEvent.click(screen.getByRole("button", { name: /set up with face id/i }));

    await waitFor(() => {
      expect(webauthn.enrollPasskey).toHaveBeenCalled();
      expect(api.registerPasskey).toHaveBeenCalledWith("test@example.com", expect.anything());
      expect(mockSetItem).toHaveBeenCalledWith("smartshop_token", "test-jwt");
      expect(mockPush).toHaveBeenCalledWith("/wallet");
    });

    mockSetItem.mockRestore();
  });

  it("Touch ID button: enrolls passkey, stores token, and redirects to /wallet", async () => {
    jest.mocked(webauthn.enrollPasskey).mockResolvedValue({} as never);
    jest.mocked(api.registerPasskey).mockResolvedValue({ token: "test-jwt" });

    const mockSetItem = jest.spyOn(Storage.prototype, "setItem");

    render(<PasskeyEnrollment />);
    fireEvent.click(screen.getByRole("button", { name: /set up with touch id/i }));

    await waitFor(() => {
      expect(webauthn.enrollPasskey).toHaveBeenCalled();
      expect(api.registerPasskey).toHaveBeenCalledWith("test@example.com", expect.anything());
      expect(mockSetItem).toHaveBeenCalledWith("smartshop_token", "test-jwt");
      expect(mockPush).toHaveBeenCalledWith("/wallet");
    });

    mockSetItem.mockRestore();
  });

  it("both buttons are disabled while enrollment is in progress", async () => {
    let resolveEnroll!: () => void;
    jest.mocked(webauthn.enrollPasskey).mockReturnValue(
      new Promise<never>((res) => { resolveEnroll = res as () => void; })
    );

    render(<PasskeyEnrollment />);
    fireEvent.click(screen.getByRole("button", { name: /set up with face id/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /setting up face id/i })).toBeDisabled();
      expect(screen.getByRole("button", { name: /set up with touch id/i })).toBeDisabled();
    });

    resolveEnroll();
  });

  it("shows error and re-enables buttons when Face ID enrollment fails", async () => {
    jest.mocked(webauthn.enrollPasskey).mockRejectedValue(new Error("User cancelled"));

    render(<PasskeyEnrollment />);
    fireEvent.click(screen.getByRole("button", { name: /set up with face id/i }));

    await waitFor(() => {
      expect(screen.getByText(/user cancelled/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /set up with face id/i })).not.toBeDisabled();
      expect(screen.getByRole("button", { name: /set up with touch id/i })).not.toBeDisabled();
    });
  });

  it("shows error and re-enables buttons when Touch ID enrollment fails", async () => {
    jest.mocked(webauthn.enrollPasskey).mockRejectedValue(new Error("Not supported"));

    render(<PasskeyEnrollment />);
    fireEvent.click(screen.getByRole("button", { name: /set up with touch id/i }));

    await waitFor(() => {
      expect(screen.getByText(/not supported/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /set up with face id/i })).not.toBeDisabled();
      expect(screen.getByRole("button", { name: /set up with touch id/i })).not.toBeDisabled();
    });
  });

  it("redirects to /login if no pending email in session", async () => {
    mockSessionStorage.getItem.mockImplementation(() => null);

    render(<PasskeyEnrollment />);

    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
  });
});
