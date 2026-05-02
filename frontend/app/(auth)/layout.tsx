export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="mb-8 text-center">
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">
            SmartShop
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            Your autonomous shopping assistant
          </p>
        </div>
        {children}
      </div>
    </div>
  );
}
