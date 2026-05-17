"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Clock, ExternalLink, Loader2, MessageSquare, Search, ShoppingCart } from "lucide-react";
import { getHistory, ApiError, type HistoryEntry } from "@/lib/api";

function intentBadge(intent: HistoryEntry["intent"]) {
  if (intent === "SEARCH")
    return (
      <span className="flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300">
        <Search className="w-3 h-3" /> Search
      </span>
    );
  if (intent === "CLARIFY")
    return (
      <span className="flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300">
        <MessageSquare className="w-3 h-3" /> Clarify
      </span>
    );
  return (
    <span className="flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400">
      <MessageSquare className="w-3 h-3" /> Chat
    </span>
  );
}

function formatDate(iso: string) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function HistoryCard({ entry }: { entry: HistoryEntry }) {
  const products = entry.response_json?.products ?? [];
  const reply = entry.response_json?.reply;

  return (
    <div className="bg-white dark:bg-gray-800 border dark:border-gray-700 rounded-2xl p-5 space-y-3">
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium text-gray-800 dark:text-gray-100 leading-snug">{entry.prompt}</p>
        <div className="flex items-center gap-2 shrink-0">
          {intentBadge(entry.intent)}
        </div>
      </div>

      <div className="flex items-center gap-1.5 text-xs text-gray-400 dark:text-gray-500">
        <Clock className="w-3 h-3" />
        {formatDate(entry.created_at)}
      </div>

      {entry.intent === "SEARCH" && products.length > 0 && (
        <div className="space-y-2 pt-1">
          {products.map((p) => (
            <a
              key={p.url}
              href={p.url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center justify-between gap-3 px-4 py-3 rounded-xl bg-gray-50 dark:bg-gray-700/50 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 transition-colors group"
            >
              <div className="flex items-center gap-3 min-w-0">
                <span className="text-xs font-bold text-indigo-500 dark:text-indigo-400 shrink-0">
                  #{p.rank}
                </span>
                <span className="text-sm font-medium text-gray-700 dark:text-gray-200 truncate">
                  {p.title}
                </span>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                {p.price != null && (
                  <span className="text-sm font-semibold text-gray-800 dark:text-gray-100">
                    {p.price} {p.currency}
                  </span>
                )}
                <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300">
                  {p.value_score.toFixed(1)}
                </span>
                <ExternalLink className="w-3.5 h-3.5 text-gray-400 group-hover:text-indigo-500" />
              </div>
            </a>
          ))}
        </div>
      )}

      {entry.intent !== "SEARCH" && reply && (
        <p className="text-sm text-gray-500 dark:text-gray-400 italic leading-relaxed">{reply}</p>
      )}
    </div>
  );
}

export default function HistoryPage() {
  const router = useRouter();
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = localStorage.getItem("smartshop_token") ?? "";
    getHistory(token)
      .then(({ entries }) => setEntries(entries))
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          localStorage.removeItem("smartshop_token");
          router.replace("/login");
          return;
        }
        setError(err instanceof Error ? err.message : "Could not load history.");
      })
      .finally(() => setLoading(false));
  }, [router]);

  return (
    <div className="h-full overflow-y-auto">
      <div className="max-w-3xl mx-auto px-8 py-8 space-y-4">
        <div className="flex items-center justify-between">
          <h1 className="text-2xl font-bold text-gray-800 dark:text-gray-100">Search History</h1>
          <button
            onClick={() => router.push("/dashboard")}
            className="flex items-center gap-2 text-sm text-indigo-600 dark:text-indigo-400 hover:underline"
          >
            <ShoppingCart className="w-4 h-4" /> New search
          </button>
        </div>

        {loading && (
          <div className="flex justify-center py-16">
            <Loader2 className="animate-spin w-8 h-8 text-indigo-600" />
          </div>
        )}

        {error && (
          <p className="text-center text-red-500 dark:text-red-400 py-8">{error}</p>
        )}

        {!loading && !error && entries.length === 0 && (
          <div className="text-center py-20 text-gray-400 dark:text-gray-500 space-y-2">
            <Search className="w-12 h-12 mx-auto opacity-40" />
            <p className="text-lg font-medium">No searches yet</p>
            <p className="text-sm">Your shopping searches will appear here.</p>
          </div>
        )}

        {entries.map((entry) => (
          <HistoryCard key={entry.id} entry={entry} />
        ))}
      </div>
    </div>
  );
}
