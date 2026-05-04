import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RegisterForm from "@/components/auth/RegisterForm";
import * as api from "@/lib/api";

const mockPush = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn() }),
}));

// Preserve real ApiError so instanceof checks inside the component work correctly
jest.mock("@/lib/api", () => {
  const { ApiError } = jest.requireActual("@/lib/api");
  return {
    ApiError,
    sendOtp: jest.fn(),
    checkEmail: jest.fn(),
    verifyOtp: jest.fn(),
    registerPasskey: jest.fn(),
    getPasskeyChallenge: jest.fn(),
    verifyPasskey: jest.fn(),
    verifyMagicLink: jest.fn(),
    getBalance: jest.fn(),
    createCheckout: jest.fn(),
  };
});

Object.defineProperty(window, "sessionStorage", {
  value: {
    getItem: jest.fn(() => null),
    setItem: jest.fn(),
    removeItem: jest.fn(),
  },
  writable: true,
});

describe("RegisterForm", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockPush.mockClear();
  });

  it("renders all required input fields including email", () => {
    render(<RegisterForm />);
    expect(screen.getByPlaceholderText("you@example.com")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("712345678")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("123 Main St")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Bucharest")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("010101")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Romania")).toBeInTheDocument();
  });

  it("renders country code select", () => {
    render(<RegisterForm />);
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("shows validation errors on empty submit", async () => {
    render(<RegisterForm />);
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));
    await waitFor(() => {
      expect(screen.getByText(/valid email/i)).toBeInTheDocument();
      expect(screen.getByText(/6–14 digits/i)).toBeInTheDocument();
      expect(screen.getByText(/street address is required/i)).toBeInTheDocument();
      expect(screen.getByText(/city is required/i)).toBeInTheDocument();
      expect(screen.getByText(/postal code is required/i)).toBeInTheDocument();
      expect(screen.getByText(/country is required/i)).toBeInTheDocument();
    });
  });

  it("clears field error on input change", async () => {
    render(<RegisterForm />);
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));
    await waitFor(() => {
      expect(screen.getByText(/city is required/i)).toBeInTheDocument();
    });
    await userEvent.type(screen.getByPlaceholderText("Bucharest"), "Bucharest");
    await waitFor(() => {
      expect(screen.queryByText(/city is required/i)).not.toBeInTheDocument();
    });
  });

  it("calls sendOtp with correct payload and navigates to verify", async () => {
    jest.mocked(api.sendOtp).mockResolvedValue({ message: "OTP sent" });

    render(<RegisterForm />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "test@example.com");
    await userEvent.type(screen.getByPlaceholderText("712345678"), "712345678");
    await userEvent.type(screen.getByPlaceholderText("123 Main St"), "123 Main St");
    await userEvent.type(screen.getByPlaceholderText("Bucharest"), "Bucharest");
    await userEvent.type(screen.getByPlaceholderText("010101"), "010101");
    await userEvent.type(screen.getByPlaceholderText("Romania"), "Romania");

    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));

    await waitFor(() => {
      expect(api.sendOtp).toHaveBeenCalledWith(
        expect.objectContaining({
          email: "test@example.com",
          phone: "+40712345678",
          street_address: "123 Main St",
          city: "Bucharest",
          postal_code: "010101",
          country: "Romania",
        })
      );
      expect(mockPush).toHaveBeenCalledWith(
        "/verify?email=test%40example.com"
      );
    });
  });

  it("shows 'already registered / log in' prompt on 409 error", async () => {
    const { ApiError } = jest.requireActual("@/lib/api");
    jest.mocked(api.sendOtp).mockRejectedValue(new ApiError("Email already registered", 409));

    render(<RegisterForm />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "dup@example.com");
    await userEvent.type(screen.getByPlaceholderText("712345678"), "712345678");
    await userEvent.type(screen.getByPlaceholderText("123 Main St"), "St");
    await userEvent.type(screen.getByPlaceholderText("Bucharest"), "City");
    await userEvent.type(screen.getByPlaceholderText("010101"), "12345");
    await userEvent.type(screen.getByPlaceholderText("Romania"), "RO");

    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));

    await waitFor(() => {
      expect(screen.getByText(/this email is already registered/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /log in instead/i })).toBeInTheDocument();
    });
  });

  it("'log in instead' button navigates to /login", async () => {
    const { ApiError } = jest.requireActual("@/lib/api");
    jest.mocked(api.sendOtp).mockRejectedValue(new ApiError("Email already registered", 409));

    render(<RegisterForm />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "dup@example.com");
    await userEvent.type(screen.getByPlaceholderText("712345678"), "712345678");
    await userEvent.type(screen.getByPlaceholderText("123 Main St"), "St");
    await userEvent.type(screen.getByPlaceholderText("Bucharest"), "City");
    await userEvent.type(screen.getByPlaceholderText("010101"), "12345");
    await userEvent.type(screen.getByPlaceholderText("Romania"), "RO");

    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /log in instead/i })).toBeInTheDocument();
    });

    fireEvent.click(screen.getByRole("button", { name: /log in instead/i }));
    expect(mockPush).toHaveBeenCalledWith("/login");
  });

  it("clears 'already registered' message when email field changes", async () => {
    const { ApiError } = jest.requireActual("@/lib/api");
    jest.mocked(api.sendOtp).mockRejectedValue(new ApiError("Email already registered", 409));

    render(<RegisterForm />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "dup@example.com");
    await userEvent.type(screen.getByPlaceholderText("712345678"), "712345678");
    await userEvent.type(screen.getByPlaceholderText("123 Main St"), "St");
    await userEvent.type(screen.getByPlaceholderText("Bucharest"), "City");
    await userEvent.type(screen.getByPlaceholderText("010101"), "12345");
    await userEvent.type(screen.getByPlaceholderText("Romania"), "RO");

    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));
    await waitFor(() =>
      expect(screen.getByText(/this email is already registered/i)).toBeInTheDocument()
    );

    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "x");
    await waitFor(() =>
      expect(screen.queryByText(/this email is already registered/i)).not.toBeInTheDocument()
    );
  });

  it("shows generic global error for non-409 failures", async () => {
    jest.mocked(api.sendOtp).mockRejectedValue(new Error("Network error"));

    render(<RegisterForm />);
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "x@example.com");
    await userEvent.type(screen.getByPlaceholderText("712345678"), "712345678");
    await userEvent.type(screen.getByPlaceholderText("123 Main St"), "St");
    await userEvent.type(screen.getByPlaceholderText("Bucharest"), "City");
    await userEvent.type(screen.getByPlaceholderText("010101"), "12345");
    await userEvent.type(screen.getByPlaceholderText("Romania"), "RO");

    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));

    await waitFor(() => {
      expect(screen.getByText(/network error/i)).toBeInTheDocument();
      expect(screen.queryByText(/log in instead/i)).not.toBeInTheDocument();
    });
  });
});
