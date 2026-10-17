"use client";

import {
  BookOpen,
  Building2,
  CalendarDays,
  ChartColumn,
  Clock,
  Inbox,
  LogOut,
  Menu,
  MessageSquare,
  Mic,
  Share2,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { BackendStatus } from "@/components/BackendStatus";
import { Logo } from "@/components/Logo";
import { type Business, getBusiness, listConversations } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { avatarGradient, cn, initials } from "@/lib/utils";

type NavItem = { label: string; href: string; icon: React.ElementType; badge?: number };

function workspaceNav(businessId: string, inboxCount: number): NavItem[] {
  const base = `/dashboard/b/${businessId}`;
  return [
    { label: "Playground", href: base, icon: MessageSquare },
    { label: "Inbox", href: `${base}/inbox`, icon: Inbox, badge: inboxCount },
    { label: "Knowledge base", href: `${base}/knowledge`, icon: BookOpen },
    { label: "Services & hours", href: `${base}/services`, icon: Clock },
    { label: "Bookings", href: `${base}/bookings`, icon: CalendarDays },
    { label: "Voice", href: `${base}/voice`, icon: Mic },
    { label: "Share", href: `${base}/share`, icon: Share2 },
    { label: "Analytics", href: `${base}/analytics`, icon: ChartColumn },
  ];
}

export function Sidebar() {
  const pathname = usePathname();
  const businessId = pathname.match(/^\/dashboard\/b\/([^/]+)/)?.[1];
  const [business, setBusiness] = useState<Business | null>(null);
  const [mobileOpen, setMobileOpen] = useState(false);
  const inboxCount = useInboxCount(businessId);

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
              {workspaceNav(businessId, inboxCount).map((item) => (
                <NavLink key={item.label} item={item} active={item.href === pathname} />
              ))}
            </div>
          </div>
        )}
      </nav>

      <div className="space-y-3 border-t border-border px-3 py-4">
        <AccountMenu />
        <div className="px-2">
          <BackendStatus />
        </div>
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

function AccountMenu() {
  const { user, logout } = useAuth();
  const router = useRouter();
  if (!user) return null;
  return (
    <div className="flex items-center gap-3 rounded-lg px-2 py-1.5">
      <span
        className={cn(
          "flex size-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-br text-xs font-bold text-white",
          avatarGradient(user.email),
        )}
      >
        {initials(user.name)}
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium">{user.name}</div>
        <div className="truncate text-xs text-muted">{user.email}</div>
      </div>
      <button
        onClick={async () => {
          await logout();
          router.replace("/login");
        }}
        className="rounded-md p-1.5 text-muted transition hover:bg-zinc-100 hover:text-foreground dark:hover:bg-zinc-800"
        aria-label="Sign out"
        title="Sign out"
      >
        <LogOut className="size-4" />
      </button>
    </div>
  );
}

/** Conversations waiting for a human — polled, and refreshed when the Inbox resolves one. */
function useInboxCount(businessId: string | undefined) {
  const [count, setCount] = useState(0);
  useEffect(() => {
    if (!businessId) return;
    const load = () =>
      listConversations(businessId, "needs_human")
        .then((list) => setCount(list.length))
        .catch(() => {});
    load();
    const timer = setInterval(load, 20000);
    window.addEventListener("voxdesk:inbox", load);
    return () => {
      clearInterval(timer);
      window.removeEventListener("voxdesk:inbox", load);
    };
  }, [businessId]);
  return count;
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const { label, href, icon: Icon, badge } = item;
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition",
        active
          ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300"
          : "text-muted hover:bg-zinc-100 hover:text-foreground dark:hover:bg-zinc-800/60",
      )}
    >
      <Icon className="size-4" />
      <span className="flex-1">{label}</span>
      {!!badge && (
        <span
          className="min-w-5 rounded-full bg-amber-100 px-1.5 py-0.5 text-center text-[11px] font-semibold tabular-nums text-amber-800 dark:bg-amber-500/20 dark:text-amber-300"
          aria-label={`${badge} waiting`}
        >
          {badge}
        </span>
      )}
    </Link>
  );
}
