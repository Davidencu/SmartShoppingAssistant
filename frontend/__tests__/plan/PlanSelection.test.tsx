import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import PlanSelection from "@/components/plan/PlanSelection";
import * as api from "@/lib/api";

const mockPush = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));
jest.mock("@/lib/api");

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

describe("PlanSelection", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    localStorage.setItem("smartshop_token", "test-token");
  });

  afterEach(() => {
    localStorage.clear();
  });

  it("renders Free and Pro plan options", () => {
    render(<PlanSelection />);
    expect(screen.getByRole("button", { name: /get started free/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /upgrade to pro/i })).toBeInTheDocument();
  });

  it("renders 2 automated checkouts in free plan description", () => {
    render(<PlanSelection />);
    expect(screen.getByText(/2 automated checkout sessions/i)).toBeInTheDocument();
  });

  it("renders unlimited automated checkouts for Pro", () => {
    render(<PlanSelection />);
    const items = screen.getAllByText(/unlimited automated checkouts/i);
    expect(items.length).toBeGreaterThanOrEqual(1);
  });

  it("selecting Free calls selectFreePlan and redirects to /dashboard", async () => {
    jest.mocked(api.selectFreePlan).mockResolvedValue({ plan: "free", checkout_credits: 2 });
    render(<PlanSelection />);
    fireEvent.click(screen.getByRole("button", { name: /get started free/i }));
    await waitFor(() => {
      expect(api.selectFreePlan).toHaveBeenCalledWith("test-token");
      expect(mockPush).toHaveBeenCalledWith("/dashboard");
    });
  });

  it("clicking Upgrade to Pro creates checkout and redirects to checkout_url", async () => {
    jest.mocked(api.createProCheckout).mockResolvedValue({
      checkout_url: "https://checkout.lemonsqueezy.com/buy/pro-test",
    });
    render(<PlanSelection />);
    fireEvent.click(screen.getByRole("button", { name: /upgrade to pro/i }));
    await waitFor(() => {
      expect(api.createProCheckout).toHaveBeenCalledWith("test-token");
      expect(window.location.href).toBe("https://checkout.lemonsqueezy.com/buy/pro-test");
    });
  });

  it("both buttons are disabled while a plan action is in progress", async () => {
    let resolve!: () => void;
    jest.mocked(api.selectFreePlan).mockReturnValue(
      new Promise<never>((res) => { resolve = res as () => void; })
    );
    render(<PlanSelection />);
    fireEvent.click(screen.getByRole("button", { name: /get started free/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /get started free/i })).toBeDisabled();
      expect(screen.getByRole("button", { name: /upgrade to pro/i })).toBeDisabled();
    });
    resolve();
  });

  it("shows error message when selectFreePlan fails", async () => {
    jest.mocked(api.selectFreePlan).mockRejectedValue(new Error("Network error"));
    render(<PlanSelection />);
    fireEvent.click(screen.getByRole("button", { name: /get started free/i }));
    await waitFor(() => {
      expect(screen.getByText(/network error/i)).toBeInTheDocument();
    });
  });

  it("shows error message when createProCheckout fails", async () => {
    jest.mocked(api.createProCheckout).mockRejectedValue(new Error("Checkout unavailable"));
    render(<PlanSelection />);
    fireEvent.click(screen.getByRole("button", { name: /upgrade to pro/i }));
    await waitFor(() => {
      expect(screen.getByText(/checkout unavailable/i)).toBeInTheDocument();
    });
  });

  it("re-enables buttons after a failed action", async () => {
    jest.mocked(api.selectFreePlan).mockRejectedValue(new Error("Failed"));
    render(<PlanSelection />);
    fireEvent.click(screen.getByRole("button", { name: /get started free/i }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /get started free/i })).not.toBeDisabled();
      expect(screen.getByRole("button", { name: /upgrade to pro/i })).not.toBeDisabled();
    });
  });
});
