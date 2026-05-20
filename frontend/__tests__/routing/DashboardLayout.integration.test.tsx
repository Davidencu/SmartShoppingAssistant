/**
 * Integration tests for app/(dashboard)/layout.tsx.
 * The layout is the auth guard for all dashboard pages:
 *   - no token → redirect to /login
 *   - token present → render children + nav
 *   - sign out clears token and redirects
 *   - Plan nav link navigates to /plan
 *   - plan badge reflects free/pro status fetched from API
 */
import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import DashboardLayout from "@/app/(dashboard)/layout";
import * as api from "@/lib/api";

const mockPush = jest.fn();
const mockReplace = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush, replace: mockReplace }),
}));

jest.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "light", setTheme: jest.fn() }),
}));

jest.mock("@/lib/api", () => ({
  getPlanStatus: jest.fn().mockResolvedValue({ plan: "free", checkout_credits: 2 }),
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status: number) {
      super(message);
      this.status = status;
    }
  },
}));

describe("DashboardLayout auth guard", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.clear();
    jest.mocked(api.getPlanStatus).mockResolvedValue({ plan: "free", checkout_credits: 2 });
  });

  // No token

  it("no token → replaces to /login", async () => {
    render(<DashboardLayout><div>child</div></DashboardLayout>);
    await waitFor(() => {
      expect(mockReplace).toHaveBeenCalledWith("/login");
    });
  });

  it("no token → does NOT render children", async () => {
    render(<DashboardLayout><div data-testid="child">child</div></DashboardLayout>);
    await waitFor(() => expect(mockReplace).toHaveBeenCalled());
    expect(screen.queryByTestId("child")).not.toBeInTheDocument();
  });

  it("no token → does NOT render nav", async () => {
    render(<DashboardLayout><div>child</div></DashboardLayout>);
    await waitFor(() => expect(mockReplace).toHaveBeenCalled());
    expect(screen.queryByText("SmartShop")).not.toBeInTheDocument();
  });

  // Token present

  it("token present → renders children", async () => {
    localStorage.setItem("smartshop_token", "valid-jwt");
    render(<DashboardLayout><div data-testid="child">content</div></DashboardLayout>);
    await waitFor(() => {
      expect(screen.getByTestId("child")).toBeInTheDocument();
    });
  });

  it("token present → does NOT redirect", async () => {
    localStorage.setItem("smartshop_token", "valid-jwt");
    render(<DashboardLayout><div>content</div></DashboardLayout>);
    await waitFor(() => expect(screen.getByText("SmartShop")).toBeInTheDocument());
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("token present → shows SmartShop nav brand", async () => {
    localStorage.setItem("smartshop_token", "valid-jwt");
    render(<DashboardLayout><div>content</div></DashboardLayout>);
    await waitFor(() => {
      expect(screen.getByText("SmartShop")).toBeInTheDocument();
    });
  });

  it("token present → shows Plan nav link", async () => {
    localStorage.setItem("smartshop_token", "valid-jwt");
    render(<DashboardLayout><div>content</div></DashboardLayout>);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /plan/i })).toBeInTheDocument();
    });
  });

  it("token present → shows Sign out button", async () => {
    localStorage.setItem("smartshop_token", "valid-jwt");
    render(<DashboardLayout><div>content</div></DashboardLayout>);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /sign out/i })).toBeInTheDocument();
    });
  });

  // Plan badge

  it("free plan → shows Free badge", async () => {
    jest.mocked(api.getPlanStatus).mockResolvedValue({ plan: "free", checkout_credits: 2 });
    localStorage.setItem("smartshop_token", "valid-jwt");
    render(<DashboardLayout><div>content</div></DashboardLayout>);
    await waitFor(() => {
      expect(screen.getByTestId("plan-badge")).toHaveTextContent("Free");
    });
  });

  it("pro plan → shows Pro badge", async () => {
    jest.mocked(api.getPlanStatus).mockResolvedValue({ plan: "pro", checkout_credits: 0 });
    localStorage.setItem("smartshop_token", "valid-jwt");
    render(<DashboardLayout><div>content</div></DashboardLayout>);
    await waitFor(() => {
      expect(screen.getByTestId("plan-badge")).toHaveTextContent("Pro");
    });
  });

  it("plan fetch failure → badge not shown", async () => {
    jest.mocked(api.getPlanStatus).mockRejectedValue(new Error("Network error"));
    localStorage.setItem("smartshop_token", "valid-jwt");
    render(<DashboardLayout><div>content</div></DashboardLayout>);
    await waitFor(() => expect(screen.getByText("SmartShop")).toBeInTheDocument());
    expect(screen.queryByTestId("plan-badge")).not.toBeInTheDocument();
  });

  // Nav actions

  it("Plan nav click → pushes to /plan", async () => {
    localStorage.setItem("smartshop_token", "valid-jwt");
    render(<DashboardLayout><div>content</div></DashboardLayout>);
    await waitFor(() => screen.getByRole("button", { name: /plan/i }));
    fireEvent.click(screen.getByRole("button", { name: /plan/i }));
    expect(mockPush).toHaveBeenCalledWith("/plan");
  });

  it("Sign out → removes token from localStorage", async () => {
    localStorage.setItem("smartshop_token", "valid-jwt");
    render(<DashboardLayout><div>content</div></DashboardLayout>);
    await waitFor(() => screen.getByRole("button", { name: /sign out/i }));
    fireEvent.click(screen.getByRole("button", { name: /sign out/i }));
    expect(localStorage.getItem("smartshop_token")).toBeNull();
  });

  it("Sign out → replaces to /login", async () => {
    localStorage.setItem("smartshop_token", "valid-jwt");
    render(<DashboardLayout><div>content</div></DashboardLayout>);
    await waitFor(() => screen.getByRole("button", { name: /sign out/i }));
    fireEvent.click(screen.getByRole("button", { name: /sign out/i }));
    expect(mockReplace).toHaveBeenCalledWith("/login");
  });

  // Children rendering

  it("renders children content inside the layout wrapper", async () => {
    localStorage.setItem("smartshop_token", "valid-jwt");
    render(
      <DashboardLayout>
        <h1>Dashboard content</h1>
      </DashboardLayout>
    );
    await waitFor(() => {
      expect(screen.getByRole("heading", { name: /dashboard content/i })).toBeInTheDocument();
    });
  });
});
