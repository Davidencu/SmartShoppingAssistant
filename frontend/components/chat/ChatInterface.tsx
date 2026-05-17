"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Bot, Loader2, ShoppingCart } from "lucide-react";
import ChatInput, { type ChatInputHandle } from "./ChatInput";
import MessageBubble, { type Message } from "./MessageBubble";
import { sendChatMessage, ApiError, type ChatMessage, type Product } from "@/lib/api";

let _idCounter = 0;
const nextId = () => `msg-${++_idCounter}`;

function TypingIndicator() {
  return (
    <div className="flex gap-4">
      <div className="w-10 h-10 rounded-full bg-gray-600 dark:bg-gray-500 flex items-center justify-center shrink-0">
        <Bot className="w-5 h-5 text-white" />
      </div>
      <div className="bg-gray-100 dark:bg-gray-700 rounded-2xl rounded-tl-sm px-5 py-4 flex items-center gap-1.5">
        {[0, 150, 300].map((delay) => (
          <span
            key={delay}
            className="w-2.5 h-2.5 bg-gray-400 dark:bg-gray-500 rounded-full animate-bounce"
            style={{ animationDelay: `${delay}ms` }}
          />
        ))}
      </div>
    </div>
  );
}

export default function ChatInterface() {
  const router = useRouter();
  const [messages, setMessages] = useState<Message[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const chatInputRef = useRef<ChatInputHandle>(null);
  // URLs to exclude on the next request (set when user clicks "Not satisfied?")
  const pendingExcludedUrls = useRef<string[]>([]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const handleSend = async (text: string, imageBase64?: string) => {
    setError(null);

    const userMsg: Message = {
      id: nextId(),
      role: "user",
      content: text,
      imagePreviewUrl: imageBase64
        ? `data:image/webp;base64,${imageBase64}`
        : undefined,
    };
    const updated = [...messages, userMsg];
    setMessages(updated);
    setIsLoading(true);

    // For assistant messages that contain product results, replace the display caption
    // with a price-enriched summary so the Router can apply the dynamic budget drop
    // when the user asks for cheaper alternatives ("find cheaper ones" → sees 1799/1950/1600 RON
    // in the previous turn → lowers budget_max to 80% of the cheapest price shown).
    const apiMessages: ChatMessage[] = updated.map((m) => {
      let content = m.content;
      if (m.role === "assistant" && m.products && m.products.length > 0) {
        const items = m.products
          .map((p, i) => {
            const price =
              p.price != null ? `${p.price} ${p.currency ?? ""}`.trim() : "price not listed";
            return `${i + 1}. ${p.title} — ${price}`;
          })
          .join("; ");
        content = `Here are the top ${m.products.length} products I found: ${items}`;
      }
      return {
        role: m.role,
        content,
        image_base64: m.role === "user" ? m.imagePreviewUrl?.split(",")[1] : undefined,
      };
    });

    try {
      const token = localStorage.getItem("smartshop_token") ?? "";
      const excludedUrls = pendingExcludedUrls.current;
      pendingExcludedUrls.current = [];
      const response = await sendChatMessage(apiMessages, token, excludedUrls.length > 0 ? excludedUrls : undefined);

      const assistantMsg: Message = {
        id: nextId(),
        role: "assistant",
        content:
          response.intent === "SEARCH"
            ? response.products && response.products.length > 0
              ? "Here are the top products ranked by value score:"
              : "I couldn't find matching products. Try adjusting your criteria."
            : response.reply ?? "",
        products: response.products ?? undefined,
        fromCache: response.from_cache,
        fallbackMessage: response.fallback_message ?? undefined,
      };
      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err: unknown) {
      if (err instanceof ApiError && err.status === 401) {
        localStorage.removeItem("smartshop_token");
        router.replace("/login");
        return;
      }
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleSelectProduct = (product: Product) => {
    // Placeholder — checkout flow will be implemented in the next phase
    console.log("Selected product:", product);
  };

  const handleNotSatisfied = (productUrls: string[]) => {
    pendingExcludedUrls.current = productUrls;
    chatInputRef.current?.prefill("I'm not satisfied because: ");
  };

  return (
    <div className="flex flex-col h-full">
      {/* Message list */}
      <div className="flex-1 overflow-y-auto w-full">
        <div className="max-w-5xl mx-auto px-8 py-6 space-y-6">
          {messages.length === 0 && !isLoading && (
            <div className="flex flex-col items-center justify-center min-h-[60vh] text-center select-none">
              <ShoppingCart className="w-20 h-20 text-indigo-300 mb-6" />
              <h2 className="text-3xl font-semibold text-gray-800 dark:text-gray-100 mb-2">
                What would you like to buy?
              </h2>
              <p className="text-lg text-gray-400 dark:text-gray-500 max-w-md">
                Tell me the product, your budget, and any preferences.
                I&apos;ll find the top options ranked by value.
              </p>
            </div>
          )}

          {messages.map((msg, idx) => {
            const isLastWithProducts =
              msg.role === "assistant" &&
              msg.products &&
              msg.products.length > 0 &&
              idx === messages.length - 1;

            return (
              <MessageBubble
                key={msg.id}
                message={msg}
                onSelectProduct={handleSelectProduct}
                onNotSatisfied={
                  isLastWithProducts
                    ? () => handleNotSatisfied(msg.products!.map((p) => p.url))
                    : undefined
                }
              />
            );
          })}

          {isLoading && <TypingIndicator />}
          {error && (
            <div className="text-center">
              <p className="text-base text-red-500 dark:text-red-400">{error}</p>
            </div>
          )}

          <div ref={bottomRef} />
        </div>
      </div>

      {/* Input */}
      <div className="shrink-0 border-t dark:border-gray-700">
        <div className="max-w-5xl mx-auto px-8 pb-6 pt-4">
          <ChatInput ref={chatInputRef} onSend={handleSend} disabled={isLoading} />
          <p className="text-center text-sm text-gray-400 dark:text-gray-600 mt-3">
            ShopperAI finds the best value — you decide whether to buy.
          </p>
        </div>
      </div>
    </div>
  );
}
