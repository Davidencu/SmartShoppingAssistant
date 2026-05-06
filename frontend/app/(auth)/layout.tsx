import ThemeToggle from "@/components/ThemeToggle";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="min-h-screen flex items-center justify-center bg-gradient-to-br from-indigo-50 to-blue-100 dark:from-gray-900 dark:to-gray-800 p-4">
      <div className="relative w-full max-w-md bg-white dark:bg-gray-800 rounded-2xl shadow-xl p-8">
        <div className="absolute top-3 right-3">
          <ThemeToggle />
        </div>
        <h1 className="text-2xl font-bold text-center text-indigo-700 dark:text-indigo-400 mb-6">
          SmartShop Assistant
        </h1>
        {children}
      </div>
    </main>
  );
}
