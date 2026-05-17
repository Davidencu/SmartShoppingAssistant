import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import ProductCard from "@/components/chat/ProductCard";
import type { Product } from "@/lib/api";

const makeProduct = (overrides: Partial<Product> = {}): Product => ({
  rank: 1,
  title: "ASUS VivoBook 16",
  url: "https://example.com/asus-vivobook",
  price: 1799,
  currency: "RON",
  image_url: "https://example.com/img.jpg",
  scores: {
    cost_efficiency: 85,
    quality_confidence: 78,
    logistics: 90,
    trust: 95,
  },
  value_score: 86.0,
  reasoning: "Excellent price-to-spec ratio with fast delivery.",
  ...overrides,
});

describe("ProductCard", () => {
  it("renders product title", () => {
    render(<ProductCard product={makeProduct()} />);
    expect(screen.getByText("ASUS VivoBook 16")).toBeInTheDocument();
  });

  it("renders rank label", () => {
    render(<ProductCard product={makeProduct({ rank: 2 })} />);
    expect(screen.getByText("#2 Best Value")).toBeInTheDocument();
  });

  it("renders price and currency", () => {
    render(<ProductCard product={makeProduct()} />);
    expect(screen.getByText(/1[,.]?799/)).toBeInTheDocument();
    expect(screen.getByText(/RON/)).toBeInTheDocument();
  });

  it("renders value score badge", () => {
    render(<ProductCard product={makeProduct({ value_score: 86.0 })} />);
    expect(screen.getByText("86/100")).toBeInTheDocument();
  });

  it("value score badge has green class for score >= 80", () => {
    render(<ProductCard product={makeProduct({ value_score: 85 })} />);
    const badge = screen.getByText("85/100");
    expect(badge.className).toMatch(/green/);
  });

  it("value score badge has yellow class for score 60–79", () => {
    render(<ProductCard product={makeProduct({ value_score: 70 })} />);
    const badge = screen.getByText("70/100");
    expect(badge.className).toMatch(/yellow/);
  });

  it("value score badge has red class for score < 60", () => {
    render(<ProductCard product={makeProduct({ value_score: 45 })} />);
    const badge = screen.getByText("45/100");
    expect(badge.className).toMatch(/red/);
  });

  it("renders all four score dimension labels", () => {
    render(<ProductCard product={makeProduct()} />);
    expect(screen.getByText(/cost efficiency/i)).toBeInTheDocument();
    expect(screen.getByText(/quality/i)).toBeInTheDocument();
    expect(screen.getByText(/logistics/i)).toBeInTheDocument();
    expect(screen.getByText(/trust/i)).toBeInTheDocument();
  });

  it("renders reasoning text", () => {
    render(<ProductCard product={makeProduct()} />);
    expect(
      screen.getByText("Excellent price-to-spec ratio with fast delivery.")
    ).toBeInTheDocument();
  });

  it("renders View Product link pointing to product URL", () => {
    render(<ProductCard product={makeProduct()} />);
    const link = screen.getByRole("link", { name: /view product/i });
    expect(link).toHaveAttribute("href", "https://example.com/asus-vivobook");
    expect(link).toHaveAttribute("target", "_blank");
  });

  it("does not render Buy Now when onSelect is not provided", () => {
    render(<ProductCard product={makeProduct()} />);
    expect(screen.queryByRole("button", { name: /buy now/i })).not.toBeInTheDocument();
  });

  it("renders Buy Now button when onSelect is provided", () => {
    render(<ProductCard product={makeProduct()} onSelect={jest.fn()} />);
    expect(screen.getByRole("button", { name: /buy now/i })).toBeInTheDocument();
  });

  it("calls onSelect with the product when Buy Now is clicked", () => {
    const onSelect = jest.fn();
    const product = makeProduct();
    render(<ProductCard product={product} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole("button", { name: /buy now/i }));
    expect(onSelect).toHaveBeenCalledWith(product);
  });

  it("renders image when image_url is provided", () => {
    render(<ProductCard product={makeProduct()} />);
    const img = screen.getByAltText("ASUS VivoBook 16");
    expect(img).toHaveAttribute("src", "https://example.com/img.jpg");
  });

  it("does not render image element when image_url is null", () => {
    render(<ProductCard product={makeProduct({ image_url: null })} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("does not render price when price is null", () => {
    render(<ProductCard product={makeProduct({ price: null, currency: null })} />);
    expect(screen.queryByText(/RON/)).not.toBeInTheDocument();
  });
});
