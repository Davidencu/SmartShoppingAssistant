import React from "react";
import { render, screen } from "@testing-library/react";
import BalanceDisplay from "@/components/wallet/BalanceDisplay";

describe("BalanceDisplay", () => {
  it("renders a formatted USD balance", () => {
    render(<BalanceDisplay balance={50} currency="USD" />);
    expect(screen.getByText("$50.00")).toBeInTheDocument();
  });

  it("renders $0.00 when balance is zero", () => {
    render(<BalanceDisplay balance={0} currency="USD" />);
    expect(screen.getByText("$0.00")).toBeInTheDocument();
  });

  it("shows top-up prompt when balance is 0", () => {
    render(<BalanceDisplay balance={0} currency="USD" />);
    expect(screen.getByText(/top up your wallet/i)).toBeInTheDocument();
  });

  it("does not show top-up prompt when balance is positive", () => {
    render(<BalanceDisplay balance={25} currency="USD" />);
    expect(screen.queryByText(/top up your wallet/i)).not.toBeInTheDocument();
  });

  it("shows top-up prompt for negative balance", () => {
    render(<BalanceDisplay balance={-1} currency="USD" />);
    expect(screen.getByText(/top up your wallet/i)).toBeInTheDocument();
  });

  it("formats large balances correctly", () => {
    render(<BalanceDisplay balance={100} currency="USD" />);
    expect(screen.getByText("$100.00")).toBeInTheDocument();
  });
});
