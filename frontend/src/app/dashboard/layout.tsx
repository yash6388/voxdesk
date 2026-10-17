import { Sidebar } from "@/components/app/Sidebar";
import { RequireAuth } from "@/lib/auth";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <div className="min-h-screen">
        <Sidebar />
        <div className="md:pl-64">
          <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">{children}</main>
        </div>
      </div>
    </RequireAuth>
  );
}
