"use client";

/**
 * Admin console shell.
 *
 * SRS 2.3 gives Cowrie Admins five roles with different privileges. The console
 * shows the operator everything and lets them try anything; the API refuses
 * what their role does not allow. That is deliberate — hiding a control is a
 * UI convenience, not a security boundary, and treating it as one is how
 * privilege checks get skipped on the server.
 *
 * The role is displayed in the header so an operator always knows which hat
 * they are wearing when a request comes back 403.
 */

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  Alert,
  Chart,
  Database,
  Home,
  IdCard,
  Settings,
  Shield,
  Swap,
  Upload,
} from "@/components/icons";
import { ConsoleShell, SystemStatus, type NavItem } from "@/components/shell/console";
import { Button, ErrorText, Spinner, cx, inputClass } from "@/components/ui";
import { CowrieMark } from "@/components/brand";
import { api, clearToken, getToken, setToken } from "@/lib/api";

type Admin = { id: string; email: string; fullName: string; role: string };

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const [admin, setAdmin] = useState<Admin | null>(null);
  const [checking, setChecking] = useState(true);
  const [counts, setCounts] = useState<{ kyc: number; disputes: number }>({ kyc: 0, disputes: 0 });
  const pathname = usePathname();
  const router = useRouter();

  const loadOverview = useCallback(async () => {
    try {
      const data = await api<{ queues: { pendingKyc: number; openDisputes: number } }>(
        "/admin/overview",
        { audience: "admin" },
      );
      setCounts({ kyc: data.queues.pendingKyc, disputes: data.queues.openDisputes });
    } catch {
      /* the badges are informational; a failure here must not block the page */
    }
  }, []);

  useEffect(() => {
    const stored = window.localStorage.getItem("cowrie.admin.profile");
    if (getToken("admin") && stored) {
      setAdmin(JSON.parse(stored) as Admin);
      void loadOverview();
    }
    setChecking(false);
  }, [loadOverview]);

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas">
        <Spinner className="h-6 w-6 text-violet-600" />
      </div>
    );
  }

  if (!admin) {
    return (
      <AdminLogin
        onSignedIn={(profile) => {
          setAdmin(profile);
          void loadOverview();
        }}
      />
    );
  }

  const nav: NavItem[] = [
    { href: "/admin", label: "Overview", icon: Home },
    { href: "/admin/transactions", label: "Transactions", icon: Swap },
    {
      href: "/admin/kyc",
      label: "KYC Queue",
      icon: IdCard,
      badge: counts.kyc || undefined,
      badgeTone: "danger",
    },
    {
      href: "/admin/disputes",
      label: "Disputes",
      icon: Alert,
      badge: counts.disputes || undefined,
      badgeTone: "warning",
    },
    { href: "/admin/reserve", label: "cUSDC Reserves", icon: Database },
    { href: "/admin/audit", label: "Regulator Export", icon: Upload },
    { href: "/admin/sanctions", label: "Sanctions Watch", icon: Shield },
    { href: "/admin/settings", label: "Settings", icon: Settings },
  ];

  return (
    <ConsoleShell
      product="Cowrie Admin"
      searchPlaceholder="Search transactions, users, disputes..."
      nav={nav}
      environment={{ label: "Production", tone: "production" }}
      user={{
        name: admin.fullName,
        role: admin.role.replace("_", " "),
        initials: admin.fullName
          .split(" ")
          .map((p) => p[0])
          .slice(0, 2)
          .join(""),
      }}
      footer={
        <div className="space-y-2">
          <SystemStatus label="System Status: Operational" />
          <button
            type="button"
            onClick={() => {
              clearToken("admin");
              window.localStorage.removeItem("cowrie.admin.profile");
              setAdmin(null);
              router.push("/admin");
            }}
            className="w-full rounded-lg px-3 py-2 text-left text-[12px] font-medium text-muted transition-colors hover:bg-canvas hover:text-ink"
          >
            Sign out
          </button>
        </div>
      }
    >
      <div key={pathname}>{children}</div>
    </ConsoleShell>
  );
}

// ---------------------------------------------------------------------------
// sign in
// ---------------------------------------------------------------------------

const DEMO_ROLES = [
  { email: "amara@cowrie.demo", role: "Admin — full access" },
  { email: "kwame@cowrie.demo", role: "Officer — export, freeze, disputes" },
  { email: "zainab@cowrie.demo", role: "Reviewer — KYC decisions" },
  { email: "david@cowrie.demo", role: "Engineer — treasury operations" },
  { email: "blessing@cowrie.demo", role: "Support — read only" },
];

function AdminLogin({ onSignedIn }: { onSignedIn: (a: Admin) => void }) {
  const [email, setEmail] = useState("amara@cowrie.demo");
  const [password, setPassword] = useState("cowrie-demo");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas grid-lines px-4">
      <div className="w-full max-w-[380px]">
        <div className="mb-6 flex items-center gap-2.5">
          <CowrieMark className="h-7 w-7 text-violet-600" />
          <span className="text-lg font-semibold tracking-tight text-heading">Cowrie Admin</span>
        </div>

        <form
          className="panel space-y-4 p-6"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            try {
              const result = await api<{ token: string; admin: Admin }>("/auth/admin/login", {
                method: "POST",
                body: { email, password },
              });
              setToken("admin", result.token);
              window.localStorage.setItem("cowrie.admin.profile", JSON.stringify(result.admin));
              onSignedIn(result.admin);
            } catch (err) {
              setError(err instanceof Error ? err.message : "Could not sign in.");
              setBusy(false);
            }
          }}
        >
          <div>
            <h1 className="text-lg font-bold text-heading">Compliance console</h1>
            <p className="mt-1 text-[13px] text-muted">
              Transaction monitoring, KYC review and reserve operations.
            </p>
          </div>

          <div className="space-y-1.5">
            <label htmlFor="email" className="block text-[13px] font-medium text-ink">
              Work email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className={inputClass}
            />
          </div>

          <div className="space-y-1.5">
            <label htmlFor="password" className="block text-[13px] font-medium text-ink">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className={inputClass}
            />
          </div>

          {error ? <ErrorText>{error}</ErrorText> : null}

          <Button type="submit" full loading={busy}>
            Sign in
          </Button>

          <div className="rounded-field bg-canvas p-3">
            <p className="text-[11px] font-semibold uppercase tracking-wide text-subtle">
              Demo accounts · password cowrie-demo
            </p>
            <ul className="mt-2 space-y-1">
              {DEMO_ROLES.map((account) => (
                <li key={account.email}>
                  <button
                    type="button"
                    onClick={() => setEmail(account.email)}
                    className={cx(
                      "w-full rounded px-1.5 py-1 text-left text-[11px] transition-colors hover:bg-white",
                      email === account.email ? "text-violet-700" : "text-muted",
                    )}
                  >
                    <span className="font-mono">{account.email}</span>
                    <span className="block text-[10px] text-subtle">{account.role}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        </form>
      </div>
    </div>
  );
}
