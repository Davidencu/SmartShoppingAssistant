import { render, screen } from "@testing-library/react";
import BalanceDisplay from "@/components/wallet/BalanceDisplay";

describe("BalanceDisplay", () => {
  it("formats zero balance correctly", () => {
    render(<BalanceDisplay availableCents={0} />);
    expect(screen.getByText("$0.00")).toBeInTheDocument();
  });

  it("formats non-zero balance correctly", () => {
    render(<BalanceDisplay availableCents={4999} />);
    expect(screen.getByText("$49.99")).toBeInTheDocument();
  });

  it("formats large balance correctly", () => {
    render(<BalanceDisplay availableCents={100000} />);
    expect(screen.getByText("$1,000.00")).toBeInTheDocument();
  });

  it("shows available balance label", () => {
    render(<BalanceDisplay availableCents={0} />);
    expect(screen.getByText(/available balance/i)).toBeInTheDocument();
  });

  it("respects custom currency", () => {
    render(<BalanceDisplay availableCents={5000} currency="EUR" />);
    expect(screen.getByText(/€/)).toBeInTheDocument();
  });
});
