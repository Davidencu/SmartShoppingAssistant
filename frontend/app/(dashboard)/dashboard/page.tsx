import { ShoppingCart } from "lucide-react";

export default function DashboardPage() {
  return (
    <div className="text-center py-16">
      <ShoppingCart className="mx-auto w-16 h-16 text-indigo-300 mb-4" />
      <h2 className="text-2xl font-bold text-gray-800 dark:text-gray-100 mb-2">What would you like to buy?</h2>
      <p className="text-gray-500 dark:text-gray-400">Product request input coming in the next phase.</p>
    </div>
  );
}
