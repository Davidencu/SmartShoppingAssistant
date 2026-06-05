import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RegisterForm from "@/components/auth/RegisterForm";
import * as api from "@/lib/api";

const mockPush = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: jest.fn() }),
}));

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
    getPlanStatus: jest.fn(),
    selectFreePlan: jest.fn(),
    createProCheckout: jest.fn(),
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

// Helpers
const fillRequired = async (overrides: Record<string, string> = {}) => {
  const defaults: Record<string, string> = {
    email: "test@example.com",
    phone: "712345678",
    city: "Bucharest",
    country: "Romania",
  };
  const values = { ...defaults, ...overrides };
  await userEvent.type(screen.getByPlaceholderText("you@example.com"), values.email);
  await userEvent.type(screen.getByPlaceholderText("712345678"), values.phone);
  await userEvent.type(screen.getByPlaceholderText("Bucharest"), values.city);
  await userEvent.type(screen.getByPlaceholderText("Romania"), values.country);
};

describe("RegisterForm — field rendering", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockPush.mockClear();
  });

  it("renders required fields: email, phone, city, country", () => {
    render(<RegisterForm />);
    expect(screen.getByPlaceholderText("you@example.com")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("712345678")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Bucharest")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Romania")).toBeInTheDocument();
  });

  it("renders the optional state field", () => {
    render(<RegisterForm />);
    expect(screen.getByPlaceholderText("e.g. Ilfov")).toBeInTheDocument();
  });

  it("state field is not required (no required attribute)", () => {
    render(<RegisterForm />);
    const stateInput = screen.getByPlaceholderText("e.g. Ilfov");
    expect(stateInput).not.toBeRequired();
  });

  it("does NOT render street address or postal code fields", () => {
    render(<RegisterForm />);
    expect(screen.queryByPlaceholderText("123 Main St")).not.toBeInTheDocument();
    expect(screen.queryByPlaceholderText("010101")).not.toBeInTheDocument();
  });

  it("renders phone country code selector", () => {
    render(<RegisterForm />);
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });
});

describe("RegisterForm — validation", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockPush.mockClear();
  });

  it("shows errors for all missing required fields on empty submit", async () => {
    render(<RegisterForm />);
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));
    await waitFor(() => {
      expect(screen.getByText(/valid email/i)).toBeInTheDocument();
      expect(screen.getByText(/6–14 digits/i)).toBeInTheDocument();
      expect(screen.getByText(/city is required/i)).toBeInTheDocument();
      expect(screen.getByText(/country is required/i)).toBeInTheDocument();
    });
  });

  it("does NOT show a validation error for missing state (it is optional)", async () => {
    render(<RegisterForm />);
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));
    await waitFor(() => {
      expect(screen.queryByText(/state.*required/i)).not.toBeInTheDocument();
    });
  });

  it("does NOT show street address or postal code validation errors", async () => {
    render(<RegisterForm />);
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));
    await waitFor(() => {
      expect(screen.queryByText(/street address is required/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/postal code is required/i)).not.toBeInTheDocument();
    });
  });

  it("clears city error once the field is filled in", async () => {
    render(<RegisterForm />);
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));
    await waitFor(() => expect(screen.getByText(/city is required/i)).toBeInTheDocument());
    await userEvent.type(screen.getByPlaceholderText("Bucharest"), "Cluj");
    await waitFor(() => expect(screen.queryByText(/city is required/i)).not.toBeInTheDocument());
  });
});

describe("RegisterForm — submission", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockPush.mockClear();
  });

  it("calls sendOtp with correct payload (no street_address, no postal_code)", async () => {
    jest.mocked(api.sendOtp).mockResolvedValue({ message: "OTP sent" });
    render(<RegisterForm />);
    await fillRequired();
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));

    await waitFor(() => {
      expect(api.sendOtp).toHaveBeenCalledWith(
        expect.objectContaining({
          email: "test@example.com",
          phone: "+40712345678",
          city: "Bucharest",
          country: "Romania",
        })
      );
      const call = jest.mocked(api.sendOtp).mock.calls[0][0] as unknown as Record<string, unknown>;
      expect(call).not.toHaveProperty("street_address");
      expect(call).not.toHaveProperty("postal_code");
    });
  });

  it("includes state in payload when the user fills it in", async () => {
    jest.mocked(api.sendOtp).mockResolvedValue({ message: "OTP sent" });
    render(<RegisterForm />);
    await fillRequired();
    await userEvent.type(screen.getByPlaceholderText("e.g. Ilfov"), "Ilfov");
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));

    await waitFor(() => {
      expect(api.sendOtp).toHaveBeenCalledWith(
        expect.objectContaining({ state: "Ilfov" })
      );
    });
  });

  it("omits state (undefined) from payload when the state field is left blank", async () => {
    jest.mocked(api.sendOtp).mockResolvedValue({ message: "OTP sent" });
    render(<RegisterForm />);
    await fillRequired();
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));

    await waitFor(() => {
      const call = jest.mocked(api.sendOtp).mock.calls[0][0] as unknown as Record<string, unknown>;
      expect(call.state).toBeUndefined();
    });
  });

  it("navigates to /verify with email after successful OTP send", async () => {
    jest.mocked(api.sendOtp).mockResolvedValue({ message: "OTP sent" });
    render(<RegisterForm />);
    await fillRequired();
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));

    await waitFor(() => {
      expect(mockPush).toHaveBeenCalledWith(
        "/verify?email=test%40example.com"
      );
    });
  });

  it("stores pending_registration_data in sessionStorage on submit", async () => {
    jest.mocked(api.sendOtp).mockResolvedValue({ message: "OTP sent" });
    render(<RegisterForm />);
    await fillRequired();
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));

    await waitFor(() => {
      expect(sessionStorage.setItem).toHaveBeenCalledWith(
        "pending_registration_data",
        expect.any(String)
      );
    });
  });
});

describe("RegisterForm — error handling", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockPush.mockClear();
  });

  it("shows 'already registered / log in' prompt on 409 error", async () => {
    const { ApiError } = jest.requireActual("@/lib/api");
    jest.mocked(api.sendOtp).mockRejectedValue(new ApiError("Email already registered", 409));

    render(<RegisterForm />);
    await fillRequired({ email: "dup@example.com" });
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));

    await waitFor(() => {
      expect(screen.getByText(/this email is already registered/i)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: /log in instead/i })).toBeInTheDocument();
    });
  });

  it("'log in instead' navigates to /login", async () => {
    const { ApiError } = jest.requireActual("@/lib/api");
    jest.mocked(api.sendOtp).mockRejectedValue(new ApiError("Email already registered", 409));

    render(<RegisterForm />);
    await fillRequired({ email: "dup@example.com" });
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /log in instead/i })).toBeInTheDocument()
    );
    fireEvent.click(screen.getByRole("button", { name: /log in instead/i }));
    expect(mockPush).toHaveBeenCalledWith("/login");
  });

  it("clears 'already registered' message when email changes", async () => {
    const { ApiError } = jest.requireActual("@/lib/api");
    jest.mocked(api.sendOtp).mockRejectedValue(new ApiError("Email already registered", 409));

    render(<RegisterForm />);
    await fillRequired({ email: "dup@example.com" });
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));

    await waitFor(() =>
      expect(screen.getByText(/this email is already registered/i)).toBeInTheDocument()
    );
    await userEvent.type(screen.getByPlaceholderText("you@example.com"), "x");
    await waitFor(() =>
      expect(screen.queryByText(/this email is already registered/i)).not.toBeInTheDocument()
    );
  });

  it("shows generic error message for non-409 failures", async () => {
    jest.mocked(api.sendOtp).mockRejectedValue(new Error("Network error"));

    render(<RegisterForm />);
    await fillRequired();
    fireEvent.submit(screen.getByRole("button", { name: /send verification/i }));

    await waitFor(() => {
      expect(screen.getByText(/network error/i)).toBeInTheDocument();
      expect(screen.queryByText(/log in instead/i)).not.toBeInTheDocument();
    });
  });
});
