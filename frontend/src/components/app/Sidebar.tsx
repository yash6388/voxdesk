"use client";

import {
  BookOpen,
  Building2,
  CalendarDays,
  ChartColumn,
  Menu,
  MessageSquare,
  Mic,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

import { BackendStatus } from "@/components/BackendStatus";
import { Logo } from "@/components/Logo";
import { type Business, getBusiness } from "@/lib/api";
import { avatarGradient, cn, initials } from "@/lib/utils";

type NavItem = { label: string; href?: string; icon: React.ElementType; soon?: boolean };

function workspaceNav(businessId: string): NavItem[] {
  const base = `/dashboard/b/${businessId}`;
  return [
    { label: "Playground", href: base, icon: MessageSquare },
    { label: "Knowledge base", href: `${base}/knowledge`, icon: BookOpen },
    { label: "Bookings", icon: CalendarDays, soon: true },
    { label: "Voice", icon: Mic, soon: true },
    { label: "Analytics", icon: ChartColumn, soon: true },
  ];
}

export function Sidebar() {
  const pathname = usePathname();
  const businessId = pathname.match(/^\/dashboard\/b\/([^/]+)/)?.[1];
  const [business, setBusiness] = useState<Business | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    if (!businessId) return;
    getBusiness(businessId)
      .then(setBusiness)
      .catch(() => setBusiness(null));
  }, [businessId]);

  // Close the mobile drawer whenever the route changes.
  useEffect(() => setMobileOpen(false), [pathname]);

  const nav = (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center px-5">
        <Logo href="/dashboard" />
      </div>

      <nav className="flex-1 space-y-6 px-3 py-2">
        <div className="space-y-1">
          <NavLink
            item={{ label: "Businesses", href: "/dashboard", icon: Building2 }}
            active={pathname === "/dashboard"}
          />
        </div>

        {businessId && (
          <div>
            <div className="mb-2 flex items-center gap-2 px-3">
              {business && (
                <span
                  className={cn(
                    "flex size-6 shrink-0 items-center justify-center rounded-md bg-gradient-to-br text-[10px] font-bold text-white",
                    avatarGradient(business.name),
                  )}
                >
                  {initials(business.name)}
                </span>
              )}
              <span className="truncate text-xs font-semibold uppercase tracking-wider text-muted">
                {business?.name ?? "Workspace"}
              </span>
            </div>
            <div className="space-y-1">
              {workspaceNav(businessId).map((item) => (
                <NavLink key={item.label} item={item} active={item.href === pathname} />
              ))}
            </div>
          </div>
        )}
      </nav>

      <div className="border-t border-border px-5 py-4">
        <BackendStatus />
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop */}
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-border bg-surface md:block">
        {nav}
      </aside>

      {/* Mobile top bar + drawer */}
      <div className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-surface/80 px-4 backdrop-blur md:hidden">
        <Logo href="/dashboard" />
        <button onClick={() => setMobileOpen(true)} aria-label="Open menu" className="p-2">
          <Menu className="size-5" />
        </button>
      </div>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-zinc-950/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 animate-fade-in border-r border-border bg-surface">
            <button
              onClick={() => setMobileOpen(false)}
              aria-label="Close menu"
              className="absolute right-3 top-4 p-2"
            >
              <X className="size-5" />
            </button>
            {nav}
          </aside>
        </div>
      )}
    </>
  );
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const { label, href, icon: Icon, soon } = item;
  const className = cn(
    "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
    active
      ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300"
      : "text-muted hover:bg-zinc-100 hover:text-foreground dark:hover:bg-zinc-800/60",
    soon && "cursor-default opacity-60 hover:bg-transparent hover:text-muted",
  );

  const content = (
    <>
      <Icon className="size-4" />
      <span className="flex-1">{label}</span>
      {soon && (
        <span className="rounded-full bg-zinc-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide dark:bg-zinc-800">
          Soon
        </span>
      )}
    </>
  );

  return href && !soon ? (
    <Link href={href} className={className}>
      {content}
    </Link>
  ) : (
    <div className={className}>{content}</div>
  );
}
