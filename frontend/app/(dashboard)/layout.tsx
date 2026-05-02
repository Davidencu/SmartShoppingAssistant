import { redirect } from "next/navigation";
import { createClient } from "@/lib/supabase/server";
import { Wallet, ShoppingBag, LogOut } from "lucide-react";
import Link from "next/link";

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const supabase = await createClient();
  const { data: { session } } = await supabase.auth.getSession();
  if (!session) redirect("/login");

  return (
    <div className="flex min-h-screen flex-col">
      <nav className="border-b border-slate-200 bg-white px-6 py-3">
        <div className="mx-auto flex max-w-5xl items-center justify-between">
          <Link href="/dashboard" className="flex items-center gap-2 font-bold text-slate-900">
            <ShoppingBag className="h-5 w-5 text-indigo-600" />
            SmartShop
          </Link>
          <div className="flex items-center gap-4">
            <Link
              href="/dashboard/wallet"
              className="flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900"
            >
              <Wallet className="h-4 w-4" />
              Wallet
            </Link>
            <form action="/auth/signout" method="post">
              <button
                type="submit"
                className="flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900"
              >
                <LogOut className="h-4 w-4" />
                Sign out
              </button>
            </form>
          </div>
        </div>
      </nav>
      <main className="flex-1 px-6 py-8">
        <div className="mx-auto max-w-5xl">{children}</div>
      </main>
    </div>
  );
}
