"use client";

import { Bot, User, DatabaseZap, ThumbsDown } from "lucide-react";
import ProductCard from "./ProductCard";
import type { Product } from "@/lib/api";

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  imagePreviewUrl?: string;
  products?: Product[];
  fromCache?: boolean;
  fallbackMessage?: string;
}

interface Props {
  message: Message;
  onSelectProduct?: (product: Product) => void;
  onNotSatisfied?: () => void;
}

export default function MessageBubble({ message, onSelectProduct, onNotSatisfied }: Props) {
  const isUser = message.role === "user";

  return (
    <div className={`flex gap-4 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar */}
      <div
        className={`shrink-0 w-10 h-10 rounded-full flex items-center justify-center text-white
          ${isUser ? "bg-indigo-600" : "bg-gray-600 dark:bg-gray-500"}`}
      >
        {isUser ? <User className="w-5 h-5" /> : <Bot className="w-5 h-5" />}
      </div>

      {/* Content */}
      <div className={`max-w-[85%] space-y-3 ${isUser ? "items-end" : "items-start"} flex flex-col`}>
        {/* Image preview (user messages only) */}
        {message.imagePreviewUrl && (
          <div
            className={`rounded-xl overflow-hidden border dark:border-gray-700
              ${isUser ? "self-end" : "self-start"}`}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={message.imagePreviewUrl}
              alt="Attached"
              className="max-w-[240px] max-h-[180px] object-cover"
            />
          </div>
        )}

        {/* Text bubble */}
        {message.content && (
          <div
            className={`px-5 py-3 rounded-2xl text-base leading-relaxed
              ${isUser
                ? "bg-indigo-600 text-white rounded-tr-sm"
                : "bg-gray-100 dark:bg-gray-700 text-gray-900 dark:text-gray-100 rounded-tl-sm"
              }`}
          >
            {message.content}
          </div>
        )}

        {/* Product cards (SEARCH results) */}
        {message.products && message.products.length > 0 && (
          <div className="w-full space-y-3">
            {/* Fallback notice — shown when results come from global shops */}
            {message.fallbackMessage && (
              <div className="flex items-start gap-2 text-sm text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 rounded-xl px-4 py-3">
                <span className="mt-0.5 shrink-0">🌍</span>
                <span>{message.fallbackMessage}</span>
              </div>
            )}

            {message.fromCache && (
              <div className="flex items-center gap-2 text-sm text-gray-400 dark:text-gray-500">
                <DatabaseZap className="w-4 h-4" />
                Results from cache
              </div>
            )}

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {message.products.map((p) => (
                <ProductCard key={p.url} product={p} onSelect={onSelectProduct} />
              ))}
            </div>

            {/* Not satisfied button — only on the last assistant message with products */}
            {onNotSatisfied && (
              <div className="flex justify-end pt-1">
                <button
                  type="button"
                  onClick={onNotSatisfied}
                  className="flex items-center gap-2 text-sm text-gray-400 dark:text-gray-500
                    hover:text-gray-600 dark:hover:text-gray-300 transition-colors"
                >
                  <ThumbsDown className="w-4 h-4" />
                  Not satisfied? Tell me what to improve
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
