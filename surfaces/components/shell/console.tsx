"use client";

/**
 * The desktop console shell.
 *
 * Shared by the Admin console, the Developer portal and the Regulator portal.
 * SRS 3.1 requires one design system across all six surfaces; sharing the
 * chrome is how that stays true as the screens diverge.
 *
 * Layout is a fixed sidebar plus a scrolling main column, matching the
 * mockups. The sidebar collapses to a top drawer below `lg`, because a
 * compliance officer checking a stuck transfer from a phone should still be
 * able to reach every section.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { CowrieMark } from "@/components/brand";
import { cx } from "@/components/ui";

export type NavItem = {
  href: string;
  label: string;
  icon: (p: { className?: string }) => React.ReactElement;
  badge?: number | string;
  badgeTone?: "danger" | "warning" | "violet";
};

export function ConsoleShell({
  product,
  nav,
  environment,
  user,
  footer,
  children,
}: {
  product: string;
  nav: NavItem[];
  environment: { label: string; tone: "production" | "sandbox" };
  user: { name: string; role: string; initials: string };
  footer: React.ReactNode;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen bg-canvas">
      {/* ---- top bar ---- */}
      <header className="sticky top-0 z-30 border-b border-line bg-white">
        <div className="flex h-16 items-center gap-4 px-4 lg:px-6">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="-ml-1 flex h-9 w-9 items-center justify-center rounded-lg text-muted lg:hidden"
            aria-label="Toggle navigation"
            aria-expanded={open}
          >
            <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
              <path d="M4 7h16M4 12h16M4 17h16" />
            </svg>
          </button>

          <Link href="/" className="flex shrink-0 items-center gap-2.5">
            <CowrieMark className="h-6 w-6 text-violet-600" />
            <span className="text-[15px] font-semibold tracking-tight text-heading">{product}</span>
          </Link>

          <div className="flex-1" />

          <div className="ml-auto flex items-center gap-3 md:ml-0">
            <EnvironmentPill {...environment} />

            <div className="flex items-center gap-2.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-full bg-violet-100 text-[11px] font-semibold text-violet-700">
                {user.initials}
              </span>
              <span className="hidden leading-tight sm:block">
                <span className="block text-[13px] font-semibold text-heading">{user.name}</span>
                <span className="block text-[10px] font-semibold uppercase tracking-wide text-violet-600">
                  {user.role}
                </span>
              </span>
            </div>

          </div>
        </div>
      </header>

      <div className="flex">
        {/* ---- sidebar ---- */}
        <aside
          className={cx(
            "z-20 w-[236px] shrink-0 border-r border-line bg-white",
            "lg:sticky lg:top-16 lg:block lg:h-[calc(100vh-4rem)]",
            open ? "fixed inset-y-16 left-0 block overflow-y-auto" : "hidden",
          )}
        >
          <nav aria-label="Sections" className="flex h-full flex-col p-3">
            <ul className="space-y-0.5">
              {nav.map((item) => {
                const active =
                  pathname === item.href ||
                  (item.href !== "/admin" &&
                    item.href !== "/developers" &&
                    item.href !== "/regulator" &&
                    pathname.startsWith(item.href));
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      onClick={() => setOpen(false)}
                      aria-current={active ? "page" : undefined}
                      className={cx(
                        "relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-[13px] font-medium transition-colors",
                        active
                          ? "bg-violet-50 text-violet-700"
                          : "text-muted hover:bg-canvas hover:text-ink",
                      )}
                    >
                      {active ? (
                        <span className="absolute inset-y-1.5 left-0 w-0.5 rounded-r bg-violet-600" />
                      ) : null}
                      <item.icon className="h-[18px] w-[18px] shrink-0" />
                      <span className="truncate">{item.label}</span>
                      {item.badge !== undefined ? (
                        <span
                          className={cx(
                            "ml-auto rounded-pill px-1.5 py-0.5 text-[10px] font-bold",
                            item.badgeTone === "danger"
                              ? "bg-danger text-white"
                              : item.badgeTone === "warning"
                                ? "bg-warning text-white"
                                : "bg-violet-100 text-violet-700",
                          )}
                        >
                          {item.badge}
                        </span>
                      ) : null}
                    </Link>
                  </li>
                );
              })}
            </ul>

            <div className="mt-auto pt-4">{footer}</div>
          </nav>
        </aside>

        {/* ---- main ---- */}
        <main id="main" className="min-w-0 flex-1">
          {children}
        </main>
      </div>
    </div>
  );
}

function EnvironmentPill({ label, tone }: { label: string; tone: "production" | "sandbox" }) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-pill px-2.5 py-1.5 text-[12px] font-semibold",
        tone === "production"
          ? "bg-success-bg text-success ring-1 ring-inset ring-success-ring"
          : "bg-warning-bg text-warning ring-1 ring-inset ring-warning-ring",
      )}
    >
      <span
        className={cx("h-1.5 w-1.5 rounded-full", tone === "production" ? "bg-success" : "bg-warning")}
      />
      {label}
    </span>
  );
}

/** The status block at the foot of the sidebar. */
export function SystemStatus({ label, tone = "success" }: { label: string; tone?: "success" | "warning" }) {
  return (
    <div
      className={cx(
        "rounded-lg px-3 py-2.5 text-[12px] font-medium",
        tone === "success" ? "bg-success-bg text-success" : "bg-warning-bg text-warning",
      )}
    >
      <span className="inline-flex items-center gap-2">
        <span className={cx("h-1.5 w-1.5 rounded-full", tone === "success" ? "bg-success" : "bg-warning")} />
        {label}
      </span>
    </div>
  );
}

/** The thin metadata strip at the bottom of every console page. */
export function ConsoleFooter({ items }: { items: string[] }) {
  return (
    <footer className="border-t border-line px-6 py-4">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-subtle">
        {items.map((item, index) => (
          <span key={item} className="flex items-center gap-2">
            {index > 0 ? <span aria-hidden="true">•</span> : null}
            <span>{item}</span>
          </span>
        ))}
      </p>
    </footer>
  );
}
