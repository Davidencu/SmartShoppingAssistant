"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { verifyMagicLink } from "@/lib/api";

export default function RootPage() {
  const router = useRouter();

  useEffect(() => {
    const hash = window.location.hash;

    if (hash) {
      const params = new URLSearchParams(hash.slice(1));
      const accessToken = params.get("access_token");
      const type = params.get("type");

      if (accessToken && (type === "signup" || type === "magiclink" || type === "email")) {
        verifyMagicLink(accessToken)
          .then((data) => {
            sessionStorage.setItem("passkey_options", JSON.stringify(data.options));
            sessionStorage.setItem("pending_email", data.email);
            router.replace("/register/passkey");
          })
          .catch(() => {
            router.replace("/register");
          });
        return;
      }
    }

    const token = localStorage.getItem("smartshop_token");
    router.replace(token ? "/dashboard" : "/login");
  }, [router]);

  return null;
}
