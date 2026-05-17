"use client";

import { useState } from "react";
import { ExternalLink, Star, Truck, Shield, DollarSign, ChevronDown, ChevronUp } from "lucide-react";
import type { Product } from "@/lib/api";

interface Props {
  product: Product;
  onSelect?: (product: Product) => void;
}

function ScoreBar({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) {
  const pct = Math.min(100, Math.max(0, value));
  const color =
    pct >= 80 ? "bg-green-500" : pct >= 55 ? "bg-yellow-500" : "bg-red-500";

  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="text-gray-400 flex items-center gap-1.5 w-32 shrink-0">
        {icon}
        {label}
      </span>
      <div className="flex-1 h-2 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right text-gray-500 dark:text-gray-400">{Math.round(pct)}</span>
    </div>
  );
}

function ValueBadge({ score }: { score: number }) {
  const rounded = Math.round(score * 10) / 10;
  const cls =
    score >= 80
      ? "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300"
      : score >= 60
      ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300"
      : "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300";

  return (
    <span className={`text-sm font-bold px-2.5 py-0.5 rounded-full ${cls}`}>
      {rounded}/100
    </span>
  );
}

export default function ProductCard({ product, onSelect }: Props) {
  const [reasoningExpanded, setReasoningExpanded] = useState(false);
  const priceStr =
    product.price != null
      ? `${product.price.toLocaleString()} ${product.currency ?? ""}`
      : null;

  return (
    <div className="border dark:border-gray-700 rounded-xl overflow-hidden bg-white dark:bg-gray-800 shadow-sm hover:shadow-md transition-shadow">
      {/* Image */}
      {product.image_url && (
        <div className="w-full h-48 bg-gray-100 dark:bg-gray-700 overflow-hidden">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={product.image_url}
            alt={product.title}
            className="w-full h-full object-contain p-3"
            onError={(e) => {
              (e.target as HTMLImageElement).style.display = "none";
            }}
          />
        </div>
      )}

      <div className="p-5 space-y-4">
        {/* Header */}
        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <p className="text-sm text-indigo-600 dark:text-indigo-400 font-semibold mb-1">
              #{product.rank} Best Value
            </p>
            <h3 className="font-semibold text-base text-gray-900 dark:text-gray-100">
              {product.title}
            </h3>
          </div>
          <ValueBadge score={product.value_score} />
        </div>

        {/* Price */}
        {priceStr && (
          <p className="text-xl font-bold text-gray-900 dark:text-gray-100">{priceStr}</p>
        )}

        {/* Score breakdown */}
        <div className="space-y-2">
          <ScoreBar
            label="Cost efficiency"
            value={product.scores.cost_efficiency}
            icon={<DollarSign className="w-3.5 h-3.5" />}
          />
          <ScoreBar
            label="Quality"
            value={product.scores.quality_confidence}
            icon={<Star className="w-3.5 h-3.5" />}
          />
          <ScoreBar
            label="Logistics"
            value={product.scores.logistics}
            icon={<Truck className="w-3.5 h-3.5" />}
          />
          <ScoreBar
            label="Trust"
            value={product.scores.trust}
            icon={<Shield className="w-3.5 h-3.5" />}
          />
        </div>

        {/* Reasoning */}
        {product.reasoning && (
          <div>
            <p className={`text-sm text-gray-500 dark:text-gray-400 leading-relaxed ${reasoningExpanded ? "" : "line-clamp-3"}`}>
              {product.reasoning}
            </p>
            <button
              onClick={() => setReasoningExpanded((v) => !v)}
              className="mt-1 flex items-center gap-0.5 text-xs text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 transition-colors"
            >
              {reasoningExpanded ? (
                <><ChevronUp className="w-3.5 h-3.5" /> Show less</>
              ) : (
                <><ChevronDown className="w-3.5 h-3.5" /> Show more</>
              )}
            </button>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 pt-1">
          <a
            href={product.url}
            target="_blank"
            rel="noopener noreferrer"
            className="flex-1 flex items-center justify-center gap-1.5 text-sm border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 rounded-lg py-2.5 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            <ExternalLink className="w-4 h-4" />
            View Product
          </a>
          {onSelect && (
            <button
              onClick={() => onSelect(product)}
              className="flex-1 text-sm bg-indigo-600 text-white rounded-lg py-2.5 font-semibold hover:bg-indigo-700 transition-colors"
            >
              Buy Now
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
