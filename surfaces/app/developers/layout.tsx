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
import { Button, ErrorText, Spinner, cx, inputClass } from "@/components/ui";
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
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
        <form
          className="w-full max-w-[360px] space-y-5"
          onSubmit={async (event) => {
            event.preventDefault();
            setBusy(true);
            setError("");
            try {
              await api("/v1/stats?days=1", { apiKey: draft.trim() });
              window.localStorage.setItem(STORE, draft.trim());
              setApiKey(draft.trim());
            } catch (err) {
              setError(err instanceof Error ? err.message : "That key was not accepted.");
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

          <h1 className="text-lg font-bold text-heading">Sign in</h1>

          <label className="block">
            <span className="mb-1.5 block text-[13px] font-medium text-ink">Secret key</span>
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder="ck_sandbox_..."
              autoComplete="off"
              spellCheck={false}
              className={cx(inputClass, "font-mono text-[12px]")}
            />
          </label>

          {error ? <ErrorText>{error}</ErrorText> : null}

          <Button type="submit" full loading={busy} disabled={!draft.trim()}>
            Continue
          </Button>
        </form>
      </div>
    );
  }

  return (
    <PortalContext.Provider value={{ apiKey }}>
      <ConsoleShell
        product="Cowrie Developers"
        searchPlaceholder="Search endpoints, request IDs..."
        nav={NAV}
        environment={{ label: "Sandbox", tone: "sandbox" }}
        user={{ name: "Adunni Pay", role: "Partner", initials: "AP" }}
        footer={
          <div className="space-y-2">
            <SystemStatus label="All systems normal" />
            <button
              type="button"
              onClick={() => {
                window.localStorage.removeItem(STORE);
                setApiKey("");
                setDraft("");
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
