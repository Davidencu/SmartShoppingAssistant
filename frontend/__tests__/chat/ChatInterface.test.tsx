import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ChatInterface from "@/components/chat/ChatInterface";
import * as api from "@/lib/api";

jest.mock("@/lib/api");
jest.mock("next/navigation", () => ({ useRouter: () => ({ replace: jest.fn() }) }));

// jsdom does not implement scrollIntoView
window.HTMLElement.prototype.scrollIntoView = jest.fn();

beforeEach(() => {
  jest.clearAllMocks();
  localStorage.setItem("smartshop_token", "test-token");
});

afterEach(() => {
  localStorage.clear();
});

const CHAT_RESPONSE: api.ChatResponse = {
  intent: "CHAT",
  reply: "Hello! I help you find and buy products.",
  products: null,
  collected_params: {
    category: null,
    budget: null,
    budget_max: null,
    budget_currency: null,
    preference: null,
  },
  from_cache: false,
  fallback_message: null,
};

const SEARCH_RESPONSE: api.ChatResponse = {
  intent: "SEARCH",
  reply: null,
  products: [
    {
      rank: 1,
      title: "ASUS VivoBook 16",
      url: "https://example.com/asus",
      price: 1799,
      currency: "RON",
      image_url: null,
      scores: { cost_efficiency: 85, quality_confidence: 78, logistics: 90, trust: 95 },
      value_score: 86.0,
      reasoning: "Best value option.",
    },
    {
      rank: 2,
      title: "Lenovo IdeaPad 5",
      url: "https://example.com/lenovo",
      price: 1950,
      currency: "RON",
      image_url: null,
      scores: { cost_efficiency: 70, quality_confidence: 82, logistics: 75, trust: 90 },
      value_score: 78.5,
      reasoning: "High quality.",
    },
    {
      rank: 3,
      title: "HP Pavilion 15",
      url: "https://example.com/hp",
      price: 1600,
      currency: "RON",
      image_url: null,
      scores: { cost_efficiency: 90, quality_confidence: 65, logistics: 80, trust: 85 },
      value_score: 79.0,
      reasoning: "Best price.",
    },
  ],
  collected_params: {
    category: "Laptop",
    budget: "2000 RON",
    budget_max: 2000,
    budget_currency: "RON",
    preference: "ASUS 16GB RAM",
  },
  from_cache: false,
  fallback_message: null,
};

describe("ChatInterface", () => {
  it("renders the empty state with a welcome message", () => {
    render(<ChatInterface />);
    expect(screen.getByText(/what would you like to buy/i)).toBeInTheDocument();
  });

  it("shows the user message after submission", async () => {
    jest.mocked(api.sendChatMessage).mockResolvedValue(CHAT_RESPONSE);
    render(<ChatInterface />);

    await userEvent.type(
      screen.getByPlaceholderText(/what are you looking for/i),
      "Hello"
    );
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(screen.getByText("Hello")).toBeInTheDocument();
    });
  });

  it("shows typing indicator while loading", async () => {
    jest.mocked(api.sendChatMessage).mockReturnValue(new Promise(() => {}));
    render(<ChatInterface />);

    await userEvent.type(
      screen.getByPlaceholderText(/what are you looking for/i),
      "hi"
    );
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    // The three animated dots appear
    const dots = document.querySelectorAll(".animate-bounce");
    expect(dots.length).toBe(3);
  });

  it("renders CHAT reply as a text bubble", async () => {
    jest.mocked(api.sendChatMessage).mockResolvedValue(CHAT_RESPONSE);
    render(<ChatInterface />);

    await userEvent.type(
      screen.getByPlaceholderText(/what are you looking for/i),
      "hello"
    );
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(
        screen.getByText("Hello! I help you find and buy products.")
      ).toBeInTheDocument();
    });
  });

  it("renders 3 product cards for SEARCH response", async () => {
    jest.mocked(api.sendChatMessage).mockResolvedValue(SEARCH_RESPONSE);
    render(<ChatInterface />);

    await userEvent.type(
      screen.getByPlaceholderText(/what are you looking for/i),
      "ASUS laptop 16GB under 2000 RON"
    );
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(screen.getByText("ASUS VivoBook 16")).toBeInTheDocument();
      expect(screen.getByText("Lenovo IdeaPad 5")).toBeInTheDocument();
      expect(screen.getByText("HP Pavilion 15")).toBeInTheDocument();
    });
  });

  it("sends the full message history with each request", async () => {
    jest
      .mocked(api.sendChatMessage)
      .mockResolvedValueOnce(CHAT_RESPONSE)
      .mockResolvedValueOnce(SEARCH_RESPONSE);

    render(<ChatInterface />);
    const textarea = screen.getByPlaceholderText(/what are you looking for/i);

    await userEvent.type(textarea, "hello");
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));
    await waitFor(() =>
      screen.getByText("Hello! I help you find and buy products.")
    );

    await userEvent.type(textarea, "ASUS laptop under 2000 RON");
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));
    await waitFor(() => screen.getByText("ASUS VivoBook 16"));

    const secondCall = jest.mocked(api.sendChatMessage).mock.calls[1];
    expect(secondCall[0].length).toBeGreaterThan(2);
  });

  it("shows an error message when the API call fails", async () => {
    jest
      .mocked(api.sendChatMessage)
      .mockRejectedValue(new Error("Service unavailable"));

    render(<ChatInterface />);
    await userEvent.type(
      screen.getByPlaceholderText(/what are you looking for/i),
      "laptop"
    );
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(screen.getByText(/service unavailable/i)).toBeInTheDocument();
    });
  });

  it("shows cache badge when from_cache is true", async () => {
    jest.mocked(api.sendChatMessage).mockResolvedValue({
      ...SEARCH_RESPONSE,
      from_cache: true,
    });
    render(<ChatInterface />);

    await userEvent.type(
      screen.getByPlaceholderText(/what are you looking for/i),
      "ASUS laptop"
    );
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(screen.getByText(/results from cache/i)).toBeInTheDocument();
    });
  });

  it("input is disabled while a request is in flight", async () => {
    jest.mocked(api.sendChatMessage).mockReturnValue(new Promise(() => {}));
    render(<ChatInterface />);

    await userEvent.type(
      screen.getByPlaceholderText(/what are you looking for/i),
      "laptop"
    );
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    expect(screen.getByPlaceholderText(/what are you looking for/i)).toBeDisabled();
  });

  it("clears the input after sending", async () => {
    jest.mocked(api.sendChatMessage).mockResolvedValue(CHAT_RESPONSE);
    render(<ChatInterface />);

    const textarea = screen.getByPlaceholderText(/what are you looking for/i);
    await userEvent.type(textarea, "hello");
    fireEvent.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() =>
      screen.getByText("Hello! I help you find and buy products.")
    );
    expect(textarea).toHaveValue("");
  });
});
