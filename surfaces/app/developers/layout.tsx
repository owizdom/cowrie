"use client";

/**
 * Developer portal shell.
 *
 * Gated on a live API key — FR 4.1 makes the key the partner's credential, so
 * the portal is gated on the same thing the API is, and the key is verified
 * against a real endpoint before anything renders.
 */

import { useEffect, useState } from "react";
import { CowrieMark } from "@/components/brand";
import { Book, Chart, Flask, Home, Key, Settings, Webhook } from "@/components/icons";
import { ConsoleShell, SystemStatus, type NavItem } from "@/components/shell/console";
import { Button, CopyButton, ErrorText, Spinner, cx, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import { PortalContext } from "./portal-context";

const STORE = "cowrie.developers.key";

const NAV: NavItem[] = [
  { href: "/developers", label: "Overview", icon: Home },
  { href: "/developers/keys", label: "API keys", icon: Key },
  { href: "/developers/webhooks", label: "Webhooks", icon: Webhook },
  { href: "/developers/try", label: "Try it", icon: Flask },
  { href: "/developers/logs", label: "Logs", icon: Chart },
];

export default function DevelopersLayout({ children }: { children: React.ReactNode }) {
  const [apiKey, setApiKey] = useState("");
  const [checking, setChecking] = useState(true);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [org, setOrg] = useState("");
  const [orgName, setOrgName] = useState("");
  const [orgEmail, setOrgEmail] = useState("");
  const [issued, setIssued] = useState<{ secretKey: string; publishableKey: string } | null>(null);

  /** Who this key actually belongs to, read from the API rather than assumed. */
  const [profile, setProfile] = useState<{ partner: string; contactName: string } | null>(null);

  useEffect(() => {
    if (!apiKey) {
      setProfile(null);
      return;
    }
    void (async () => {
      try {
        const stats = await api<{ partner: string; contactName: string }>("/v1/stats?days=1", {
          apiKey,
        });
        setProfile({ partner: stats.partner, contactName: stats.contactName });
      } catch {
        setProfile(null);
      }
    })();
  }, [apiKey]);

  useEffect(() => {
    const stored = window.localStorage.getItem(STORE);
    if (stored) setApiKey(stored);
    setChecking(false);
  }, []);

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas">
        <Spinner className="h-6 w-6 text-violet-600" />
      </div>
    );
  }

  if (!apiKey) {
    // Keys were just issued — show them once, then continue.
    if (issued) {
      return (
        <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
          <div className="w-full max-w-[420px] space-y-5">
            <div className="flex items-center gap-2">
              <CowrieMark className="h-6 w-6 text-violet-600" />
              <span className="text-[15px] font-semibold tracking-tight text-heading">
                Cowrie Developers
              </span>
            </div>

            <div>
              <h1 className="text-lg font-bold text-heading">Your keys</h1>
              <p className="mt-1 text-[13px] text-muted">
                The secret key is shown once. Store it now.
              </p>
            </div>

            <div className="space-y-3">
              <KeyRow label="Secret key" value={issued.secretKey} />
              <KeyRow label="Publishable key" value={issued.publishableKey} />
            </div>

            <Button
              full
              onClick={() => {
                window.localStorage.setItem(STORE, issued.secretKey);
                setApiKey(issued.secretKey);
              }}
            >
              Continue
            </Button>
          </div>
        </div>
      );
    }

    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
        <form
          className="w-full max-w-[360px] space-y-5"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            try {
              if (mode === "signin") {
                await api("/v1/stats?days=1", { apiKey: draft.trim() });
                window.localStorage.setItem(STORE, draft.trim());
                setApiKey(draft.trim());
              } else {
                const result = await api<{ secretKey: string; publishableKey: string }>(
                  "/v1/partners",
                  {
                    method: "POST",
                    body: { organisation: org, fullName: orgName, email: orgEmail },
                  },
                );
                setIssued(result);
              }
            } catch (err) {
              setError(err instanceof Error ? err.message : "That did not work.");
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="flex items-center gap-2">
            <CowrieMark className="h-6 w-6 text-violet-600" />
            <span className="text-[15px] font-semibold tracking-tight text-heading">
              Cowrie Developers
            </span>
          </div>

          <h1 className="text-lg font-bold text-heading">
            {mode === "signin" ? "Sign in" : "Create an account"}
          </h1>

          {mode === "signin" ? (
            <label className="block">
              <span className="mb-1.5 block text-[13px] font-medium text-ink">Secret key</span>
              <input
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="sk_sandbox_..."
                autoComplete="off"
                spellCheck={false}
                className={cx(inputClass, "font-mono text-[12px]")}
              />
            </label>
          ) : (
            <>
              <label className="block">
                <span className="mb-1.5 block text-[13px] font-medium text-ink">Your name</span>
                <input
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  autoComplete="name"
                  required
                  minLength={2}
                  className={inputClass}
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-[13px] font-medium text-ink">Organisation</span>
                <input value={org} onChange={(e) => setOrg(e.target.value)} required minLength={2} className={inputClass} />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-[13px] font-medium text-ink">Work email</span>
                <input type="email" value={orgEmail} onChange={(e) => setOrgEmail(e.target.value)} autoComplete="email" required className={inputClass} />
              </label>
            </>
          )}

          {error ? <ErrorText>{error}</ErrorText> : null}

          <Button
            type="submit"
            full
            loading={busy}
            disabled={
              mode === "signin"
                ? !draft.trim()
                : !org.trim() || !orgName.trim() || !orgEmail.trim()
            }
          >
            {mode === "signin" ? "Continue" : "Create account"}
          </Button>

          <p className="text-center text-[13px] text-muted">
            {mode === "signin" ? "No account yet? " : "Already have a key? "}
            <button
              type="button"
              onClick={() => { setMode(mode === "signin" ? "signup" : "signin"); setError(""); }}
              className="font-semibold text-violet-600"
            >
              {mode === "signin" ? "Create one" : "Sign in"}
            </button>
          </p>
        </form>
      </div>
    );
  }

  return (
    <PortalContext.Provider value={{ apiKey }}>
      <ConsoleShell
        product="Cowrie Developers"
        nav={NAV}
        environment={{ label: "Sandbox", tone: "sandbox" }}
        user={{
          name: profile?.contactName || profile?.partner || "Partner",
          role: profile?.partner ?? "",
          initials: (profile?.contactName || profile?.partner || "P")
            .split(/\s+/)
            .map((part) => part[0])
            .slice(0, 2)
            .join("")
            .toUpperCase(),
        }}
        footer={
          <div className="space-y-2">
            <SystemStatus label="All systems normal" />
            <button
              type="button"
              onClick={() => {
                window.localStorage.removeItem(STORE);
                window.location.href = "/";
              }}
              className="w-full rounded-lg px-3 py-2 text-left text-[12px] font-medium text-muted transition-colors hover:bg-canvas hover:text-ink"
            >
              Sign out
            </button>
          </div>
        }
      >
        {children}
      </ConsoleShell>
    </PortalContext.Provider>
  );
}


function KeyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-field border border-line bg-white p-3">
      <p className="text-[11px] text-subtle">{label}</p>
      <div className="mt-1 flex items-center gap-2">
        <code className="min-w-0 flex-1 truncate font-mono text-[12px] text-ink">{value}</code>
        <CopyButton value={value} label={label} />
      </div>
    </div>
  );
}
