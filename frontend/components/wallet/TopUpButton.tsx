"use client";

import { useEffect } from "react";
import { PlusCircle } from "lucide-react";

interface Props {
  userId: string;
}

declare global {
  interface Window {
    createLemonSqueezy?: () => void;
    LemonSqueezy?: {
      Url: { Open: (url: string) => void };
      Setup: (opts: { eventHandler: (event: { event: string }) => void }) => void;
    };
  }
}

const STORE_URL = process.env.NEXT_PUBLIC_LEMONSQUEEZY_TOPUP_URL ?? "";

export default function TopUpButton({ userId }: Props) {
  useEffect(() => {
    const script = document.createElement("script");
    script.src = "https://app.lemonsqueezy.com/js/lemon.js";
    script.defer = true;
    document.head.appendChild(script);
    return () => { document.head.removeChild(script); };
  }, []);

  function openCheckout() {
    const url = `${STORE_URL}?checkout[custom][user_id]=${userId}`;
    if (window.createLemonSqueezy) {
      window.createLemonSqueezy();
      window.LemonSqueezy?.Setup({
        eventHandler: (event) => {
          if (event.event === "Checkout.Success") {
            window.location.reload();
          }
        },
      });
      window.LemonSqueezy?.Url.Open(url);
    } else {
      window.open(url, "_blank");
    }
  }

  return (
    <button
      onClick={openCheckout}
      className="flex items-center gap-2 rounded-lg border border-indigo-200 bg-indigo-50 px-4 py-2 text-sm font-medium text-indigo-700 hover:bg-indigo-100"
    >
      <PlusCircle className="h-4 w-4" />
      Add funds
    </button>
  );
}
