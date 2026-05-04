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

describe("LoginForm", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockPush.mockClear();
    mockReplace.mockClear();
  });

  it("renders email input and continue button", () => {
    render(<LoginForm />);
    expect(screen.getByPlaceholderText("you@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /continue/i })).toBeInTheDocument();
  });

  it("shows validation error for empty submit", async () => {
    render(<LoginForm />);
    fireEvent.submit(screen.getByRole("button", { name: /continue/i }));
    await waitFor(() => {
      expect(screen.getByText(/email is required/i)).toBeInTheDocument();
    });
  });

  it("shows validation error for invalid email format", async () => {
    render(<LoginForm />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "notanemail");
    fireEvent.submit(screen.getByRole("button", { name: /continue/i }));
    await waitFor(() => {
      expect(screen.getByText(/valid email/i)).toBeInTheDocument();
    });
  });

  it("redirects to /register if email is not found", async () => {
    jest.mocked(api.checkEmail).mockResolvedValue({ exists: false });

    render(<LoginForm />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "new@example.com");
    fireEvent.submit(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(api.checkEmail).toHaveBeenCalledWith("new@example.com");
      expect(mockPush).toHaveBeenCalledWith("/register");
    });
  });

  it("triggers passkey auth and stores token if email exists", async () => {
    jest.mocked(api.checkEmail).mockResolvedValue({ exists: true });
    jest.mocked(api.getPasskeyChallenge).mockResolvedValue({ options: {} });
    jest.mocked(webauthn.authenticatePasskey).mockResolvedValue({} as never);
    jest.mocked(api.verifyPasskey).mockResolvedValue({ token: "jwt-token" });

    const mockSetItem = jest.spyOn(Storage.prototype, "setItem");

    render(<LoginForm />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "user@example.com");
    fireEvent.submit(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(mockSetItem).toHaveBeenCalledWith("smartshop_token", "jwt-token");
      expect(mockPush).toHaveBeenCalledWith("/dashboard");
    });

    mockSetItem.mockRestore();
  });

  it("shows error when passkey auth fails", async () => {
    jest.mocked(api.checkEmail).mockResolvedValue({ exists: true });
    jest.mocked(api.getPasskeyChallenge).mockRejectedValue(new Error("Auth failed"));

    render(<LoginForm />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "user@example.com");
    fireEvent.submit(screen.getByRole("button", { name: /continue/i }));

    await waitFor(() => {
      expect(screen.getByText(/auth failed/i)).toBeInTheDocument();
    });
  });
});
