import { NextResponse } from "next/server";
import { createClient } from "@/lib/supabase/server";
import { createProfile, profileExists } from "@/lib/api";

export async function GET(request: Request) {
  const { searchParams, origin } = new URL(request.url);
  const code = searchParams.get("code");
  const next = searchParams.get("next") ?? "/dashboard";

  if (!code) {
    return NextResponse.redirect(new URL("/login?error=missing_code", origin));
  }

  const supabase = await createClient();
  const { data, error } = await supabase.auth.exchangeCodeForSession(code);

  if (error || !data.session) {
    return NextResponse.redirect(new URL("/login?error=auth_failed", origin));
  }

  const { session } = data;
  const meta = session.user.user_metadata as {
    full_name?: string;
    phone?: string;
    pending_address?: {
      recipient_name: string;
      street: string;
      city: string;
      state?: string;
      country: string;
      zip_code: string;
    };
  };

  if (meta?.full_name && meta?.phone && meta?.pending_address) {
    try {
      const exists = await profileExists(session.access_token);
      if (!exists) {
        await createProfile(session.access_token, {
          full_name: meta.full_name,
          phone: meta.phone,
          address: meta.pending_address,
        });
      }
    } catch {
      // non-fatal — user can still proceed
    }
  }

  return NextResponse.redirect(new URL(next, origin));
}
