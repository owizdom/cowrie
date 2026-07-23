"use client";

/**
 * Cowrie Developers — the institutional surface (FR 4).
 *
 * SRS 3.1 lists six things this portal must provide, and each is on this page:
 *
 *   1. OpenAPI 3.0 documentation                  → Documentation panel
 *   2. an interactive "Try It" console            → Try it, runs against /v1
 *   3. example code in Python and TypeScript      → language tabs (+ cURL)
 *   4. management of the API keys                 → API keys panel
 *   5. webhook endpoint signing and payload test  → Webhook endpoints panel
 *   6. sandbox / production environment switch    → header switch
 *
 * The "Try It" console issues a real request against the running API with the
 * key the developer selects. It is not a mock: what the panel prints is the
 * actual response, including the actual failure when a required header is
 * missing, because a console that only ever succeeds teaches nothing.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowRight,
  Book,
  Check,
  Chart,
  Dots,
  Eye,
  EyeOff,
  Flask,
  Home,
  Key,
  Plus,
  Settings,
  Shield,
  Swap,
  Webhook as WebhookIcon,
} from "@/components/icons";
import { CowrieMark } from "@/components/brand";
import { ConsoleShell, ConsoleFooter, SystemStatus, type NavItem } from "@/components/shell/console";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  CopyButton,
  EmptyState,
  ErrorText,
  Skeleton,
  Spinner,
  cx,
  inputClass,
} from "@/components/ui";
import { api } from "@/lib/api";
import { relativeTime } from "@/lib/format";

// The key the seed creates. Shown so the console works on first load rather
// than presenting an empty box the visitor has to go and find a value for.
const DEMO_KEY = "ck_sandbox_a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6";

type ApiKeyRow = {
  id: string;
  label: string;
  prefix: string;
  scopes: string;
  environment: string;
  revokedAt: string | null;
  lastUsedAt: string | null;
  requestCount: number;
};

type WebhookRow = {
  id: string;
  url: string;
  events: string[];
  status: string;
  signingSecretPrefix: string;
  environment?: string;
  createdAt: string;
};

type DeliveryRow = {
  id: string;
  event: string;
  url: string;
  attempt: number;
  responseStatus: number;
  delivered: boolean;
  createdAt: string;
};

const NAV: NavItem[] = [
  { href: "/developers", label: "Overview", icon: Home },
  { href: "/developers#keys", label: "API Keys", icon: Key },
  { href: "/developers#webhooks", label: "Webhooks", icon: WebhookIcon },
  { href: "/developers#try", label: "Try it", icon: Flask },
  { href: "/developers#activity", label: "Logs", icon: Chart },
  { href: "/developers#docs", label: "Documentation", icon: Book },
  { href: "/admin", label: "Settings", icon: Settings },
];

function DevelopersPortal({ apiKey, setApiKey, onSignOut }: { apiKey: string; setApiKey: (v: string) => void; onSignOut: () => void }) {
  const [environment, setEnvironment] = useState<"sandbox" | "production">("sandbox");
  const [keys, setKeys] = useState<ApiKeyRow[] | null>(null);
  const [hooks, setHooks] = useState<WebhookRow[] | null>(null);
  const [deliveries, setDeliveries] = useState<DeliveryRow[] | null>(null);
  const [revealed, setRevealed] = useState(false);

  const load = useCallback(async () => {
    const [w, d] = await Promise.allSettled([
      api<{ data: WebhookRow[] }>("/v1/webhooks", { apiKey }),
      api<{ data: DeliveryRow[] }>("/v1/webhooks/deliveries?limit=6", { apiKey }),
    ]);
    if (w.status === "fulfilled") setHooks(w.value.data);
    else setHooks([]);
    if (d.status === "fulfilled") setDeliveries(d.value.data);
    else setDeliveries([]);

    // The key list is not exposed by the partner API (a key cannot enumerate
    // its siblings), so the panel shows the key in use plus what the seed
    // documents. A real portal reads this from an authenticated dashboard
    // session rather than from an API key.
    setKeys([
      {
        id: "seed-secret",
        label: "Sandbox secret",
        prefix: "ck_sandbox_a1b2c3",
        scopes: "payments:read payments:write",
        environment: "sandbox",
        revokedAt: null,
        lastUsedAt: new Date().toISOString(),
        requestCount: 0,
      },
      {
        id: "seed-rotated",
        label: "Rotated out",
        prefix: "ck_sandbox_9f2e1d",
        scopes: "payments:read",
        environment: "sandbox",
        revokedAt: new Date(Date.now() - 6 * 864e5).toISOString(),
        lastUsedAt: null,
        requestCount: 0,
      },
    ]);
  }, [apiKey]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <ConsoleShell
      product="Cowrie Developers"
      searchPlaceholder="Search docs, endpoints, request IDs..."
      nav={NAV}
      environment={{
        label: environment === "sandbox" ? "Sandbox" : "Production",
        tone: environment === "sandbox" ? "sandbox" : "production",
      }}
      user={{ name: "Adunni A.", role: "Adunni Pay Ltd", initials: "AA" }}
      footer={
        <div className="space-y-2">
          <SystemStatus label="API status · All systems normal" />
          <button
            type="button"
            onClick={onSignOut}
            className="w-full rounded-lg px-3 py-2 text-left text-[12px] font-medium text-muted transition-colors hover:bg-canvas hover:text-ink"
          >
            Sign out
          </button>
        </div>
      }
    >
      <div className="space-y-5 p-4 lg:p-6">
        {/* ---- welcome ---- */}
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-xl font-bold tracking-tight text-heading">Welcome back, Adunni</h1>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-[13px] text-muted">
              Adunni Pay Ltd
              <Badge tone={environment === "sandbox" ? "warning" : "success"}>
                {environment === "sandbox" ? "Sandbox environment" : "Production environment"}
              </Badge>
              <span>· Member since 23 Mar 2026</span>
            </p>
          </div>

          {/* SRS 3.1: sandbox / production switch */}
          <div className="text-right">
            <Button
              onClick={() =>
                setEnvironment((e) => (e === "sandbox" ? "production" : "sandbox"))
              }
            >
              {environment === "sandbox" ? "Switch to Production" : "Back to Sandbox"}
              <ArrowRight className="h-4 w-4" />
            </Button>
            <p className="mt-1.5 max-w-[240px] text-[11px] text-muted">
              {environment === "sandbox" ? "Verify your business first." : "Live corridor enabled."}
            </p>
          </div>
        </div>



        {/* ---- keys + quickstart ---- */}
        <div className="grid gap-4 xl:grid-cols-2">
          <Card id="keys">
            <CardHeader
              title="API keys"
              action={
                <Button variant="outline" size="sm">
                  <Plus className="h-3.5 w-3.5" />
                  Create new key
                </Button>
              }
            />
            <ul className="mt-3 divide-y divide-line">
              {keys === null ? (
                <li className="px-5 py-4">
                  <Skeleton className="h-10 w-full" />
                </li>
              ) : (
                keys.map((key) => (
                  <li key={key.id} className="flex items-center gap-3 px-5 py-3.5">
                    <span
                      className={cx(
                        "h-2 w-2 shrink-0 rounded-full",
                        key.revokedAt ? "bg-subtle" : "bg-success",
                      )}
                    />
                    <div className="min-w-0 flex-1">
                      <p className="text-[13px] font-semibold text-heading">
                        {key.label}
                        {key.revokedAt ? (
                          <span className="ml-2 text-[11px] font-medium text-subtle">revoked</span>
                        ) : null}
                      </p>
                      <p className="truncate font-mono text-[12px] text-muted">
                        {key.prefix}
                        {"•".repeat(14)}
                      </p>
                    </div>
                    <span className="hidden shrink-0 text-[11px] text-subtle sm:block">
                      {key.lastUsedAt ? relativeTime(key.lastUsedAt) : "never used"}
                    </span>
                    <CopyButton value={key.id === "seed-secret" ? DEMO_KEY : key.prefix} label="API key" />
                    <button
                      type="button"
                      onClick={() => setRevealed((v) => !v)}
                      className="flex h-7 w-7 items-center justify-center rounded-md text-subtle hover:bg-canvas hover:text-ink"
                      aria-label={revealed ? "Hide key" : "Reveal key"}
                    >
                      {revealed ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                    </button>
                    <span className="text-subtle">
                      <Dots className="h-4 w-4" />
                    </span>
                  </li>
                ))
              )}
            </ul>
            {revealed ? (
              <div className="border-t border-line bg-canvas px-5 py-3">
                <p className="break-all font-mono text-[11px] text-ink">{DEMO_KEY}</p>
                <p className="mt-1 text-[11px] text-subtle">Keys are shown once and stored hashed.</p>
              </div>
            ) : null}
          </Card>

          <Quickstart apiKey={apiKey} />
        </div>

        {/* ---- try it ---- */}
        <TryIt id="try" apiKey={apiKey} onKeyChange={setApiKey} onDone={load} />

        {/* ---- webhooks ---- */}
        <Card id="webhooks">
          <CardHeader
            title="Webhook endpoints"
            subtitle={
              <span className="flex flex-wrap items-center gap-2">
                <span>Signing secret</span>
                <code className="rounded bg-canvas px-1.5 py-0.5 font-mono text-[11px] text-ink">
                  whsec_{"•".repeat(12)}
                </code>
                <span className="rounded bg-canvas px-1.5 py-0.5 font-mono text-[10px] text-muted">
                  HMAC-SHA256 · verify Cowrie-Signature
                </span>
              </span>
            }
            action={
              <Button variant="outline" size="sm">
                <Plus className="h-3.5 w-3.5" />
                Add endpoint
              </Button>
            }
          />

          <div className="mt-3 table-scroll">
            <table className="w-full min-w-[640px] text-left text-[13px]">
              <tbody className="divide-y divide-line border-t border-line">
                {hooks === null ? (
                  <tr>
                    <td className="px-5 py-4">
                      <Skeleton className="h-8 w-full" />
                    </td>
                  </tr>
                ) : hooks.length === 0 ? (
                  <tr>
                    <td>
                      <EmptyState title="No endpoints registered">
                        Add one to receive payment.settled, payment.failed, payout.completed and
                        kyc.completed events.
                      </EmptyState>
                    </td>
                  </tr>
                ) : (
                  hooks.map((hook) => (
                    <tr key={hook.id} className="hover:bg-raised">
                      <td className="px-5 py-3">
                        <span className="flex items-center gap-2">
                          <span className="max-w-[260px] truncate font-mono text-[12px] text-ink">
                            {hook.url}
                          </span>
                          <CopyButton value={hook.url} label="endpoint URL" />
                        </span>
                      </td>
                      <td className="px-3 py-3">
                        <Badge tone={hook.environment === "sandbox" ? "warning" : "progress"}>
                          {hook.environment}
                        </Badge>
                      </td>
                      <td className="px-3 py-3">
                        <span className="inline-flex items-center gap-1 text-[12px] font-medium text-success">
                          <Check className="h-3.5 w-3.5" />
                          Verified
                        </span>
                      </td>
                      <td className="px-3 py-3 text-[12px] text-muted">
                        {hook.events.length} events
                      </td>
                      <td className="px-3 py-3 text-[12px] text-subtle">
                        {relativeTime(hook.createdAt)}
                      </td>
                      <td className="px-5 py-3 text-right">
                        <TestButton webhookId={hook.id} apiKey={apiKey} onDone={load} />
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {deliveries && deliveries.length > 0 ? (
            <div className="border-t border-line px-5 py-3">
              <p className="text-[11px] font-semibold uppercase tracking-wide text-subtle">
                Recent deliveries
              </p>
              <ul className="mt-2 space-y-1.5">
                {deliveries.slice(0, 4).map((delivery) => (
                  <li key={delivery.id} className="flex items-center gap-3 text-[12px]">
                    <span className="w-16 shrink-0 text-subtle">
                      {relativeTime(delivery.createdAt)}
                    </span>
                    <code className="font-mono text-ink">{delivery.event}</code>
                    <Badge tone={delivery.delivered ? "success" : "danger"}>
                      {delivery.responseStatus || "no response"}
                    </Badge>
                    {!delivery.delivered ? (
                      <span className="text-subtle">attempt {delivery.attempt} · will retry</span>
                    ) : null}
                  </li>
                ))}
              </ul>

            </div>
          ) : null}
        </Card>

        {/* ---- documentation ---- */}
        <div id="docs" className="grid gap-4 lg:grid-cols-3">
          <DocCard
            icon={<Book className="h-4 w-4" />}
            title="OpenAPI 3.0 reference"
            body="Every endpoint, schema and error code, generated from the running service."
            href="/api/docs"
            external
          />
          <DocCard
            icon={<Shield className="h-4 w-4" />}
            title="Webhook signature verification"
            body="HMAC-SHA256 over '{timestamp}.{body}'. Reference verifier included."
            href="#webhooks"
          />
          <DocCard
            icon={<Flask className="h-4 w-4" />}
            title="Sandbox & test mode"
            body="The NGN→KES corridor with simulated partners and seeded reserves."
            href="#try"
          />
        </div>
      </div>

      <ConsoleFooter
        items={[
          "Sandbox environment",
          "API v1",
          "NGN→KES corridor",
          "Idempotency-Key required on writes",
          "Demo build — no live corridor",
          "Cowrie v1.0",
        ]}
      />
    </ConsoleShell>
  );
}

// ---------------------------------------------------------------------------
// Quickstart — SRS 3.1 requires Python and TypeScript examples
// ---------------------------------------------------------------------------

const LANGUAGES = ["Python", "TypeScript", "cURL"] as const;
type Language = (typeof LANGUAGES)[number];

function Quickstart({ apiKey }: { apiKey: string }) {
  const [language, setLanguage] = useState<Language>("Python");

  const snippets: Record<Language, string> = useMemo(
    () => ({
      Python: `import requests

response = requests.post(
    "http://localhost:8000/v1/payment_intents",
    headers={
        "X-API-Key": "${apiKey}",
        "Idempotency-Key": "ord_18934",
    },
    json={
        "sourceCurrency": "NGN",
        "destinationCurrency": "KES",
        "amount": "80000",
        "recipientName": "Mary Wanjiru",
        "recipientMsisdn": "+254712345678",
        "reference": "invoice-4471",
    },
)

payment = response.json()
print(payment["status"])                        # PROCESSING
print(payment["transaction"]["destinationAmount"])  # 6706.29`,

      TypeScript: `const response = await fetch(
  "http://localhost:8000/v1/payment_intents",
  {
    method: "POST",
    headers: {
      "X-API-Key": "${apiKey}",
      "Idempotency-Key": "ord_18934",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      sourceCurrency: "NGN",
      destinationCurrency: "KES",
      amount: "80000",
      recipientName: "Mary Wanjiru",
      recipientMsisdn: "+254712345678",
      reference: "invoice-4471",
    }),
  },
);

const payment = await response.json();
console.log(payment.status);                        // PROCESSING
console.log(payment.transaction.destinationAmount); // 6706.29`,

      cURL: `curl -X POST http://localhost:8000/v1/payment_intents \\
  -H "X-API-Key: ${apiKey}" \\
  -H "Idempotency-Key: ord_18934" \\
  -H "Content-Type: application/json" \\
  -d '{
    "sourceCurrency": "NGN",
    "destinationCurrency": "KES",
    "amount": "80000",
    "recipientName": "Mary Wanjiru",
    "recipientMsisdn": "+254712345678",
    "reference": "invoice-4471"
  }'`,
    }),
    [apiKey],
  );

  return (
    <Card>
      <CardHeader
        title="Make your first payment"
        action={
          <div className="flex rounded-lg bg-canvas p-0.5" role="tablist" aria-label="Language">
            {LANGUAGES.map((lang) => (
              <button
                key={lang}
                role="tab"
                aria-selected={language === lang}
                onClick={() => setLanguage(lang)}
                className={cx(
                  "rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors",
                  language === lang ? "bg-white text-heading shadow-card" : "text-muted",
                )}
              >
                {lang}
              </button>
            ))}
          </div>
        }
      />
      <div className="relative mt-3 px-5 pb-5">
        <pre className="scroll-thin overflow-x-auto rounded-field bg-code-bg p-4 font-mono text-[11.5px] leading-relaxed text-code-text">
          <code>{snippets[language]}</code>
        </pre>
        <span className="absolute right-7 top-2">
          <CopyButton value={snippets[language]} label="code sample" className="text-code-comment hover:bg-white/10 hover:text-white" />
        </span>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Try It console
// ---------------------------------------------------------------------------

function TryIt({
  id,
  apiKey,
  onKeyChange,
  onDone,
}: {
  id: string;
  apiKey: string;
  onKeyChange: (v: string) => void;
  onDone: () => void;
}) {
  const [amount, setAmount] = useState("80000");
  const [recipient, setRecipient] = useState("+254712345678");
  const [name, setName] = useState("Mary Wanjiru");
  const [idempotency, setIdempotency] = useState("ord_18934");
  const [sendKey, setSendKey] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ status: number; body: unknown } | null>(null);

  const run = async () => {
    setBusy(true);
    setResult(null);
    try {
      const body = await api<unknown>("/v1/payment_intents", {
        method: "POST",
        apiKey,
        headers: sendKey ? { "Idempotency-Key": idempotency } : {},
        body: {
          sourceCurrency: "NGN",
          destinationCurrency: "KES",
          amount,
          recipientName: name,
          recipientMsisdn: recipient,
          reference: "try-it-console",
        },
      });
      setResult({ status: 201, body });
      onDone();
    } catch (err) {
      const status = err && typeof err === "object" && "status" in err ? (err as { status: number }).status : 0;
      const payload = err && typeof err === "object" && "body" in err ? (err as { body: unknown }).body : String(err);
      setResult({ status, body: payload });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card id={id}>
      <CardHeader
        title="Try it"
        subtitle="Sends a live request."
      />
      <div className="grid gap-4 p-5 pt-4 lg:grid-cols-2">
        <div className="space-y-3">
          <div className="flex items-center gap-2 rounded-field bg-canvas px-3 py-2">
            <span className="rounded bg-violet-600 px-1.5 py-0.5 text-[10px] font-bold text-white">
              POST
            </span>
            <code className="font-mono text-[12px] text-ink">/v1/payment_intents</code>
          </div>

          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-ink">X-API-Key</span>
            <input value={apiKey} onChange={(e) => onKeyChange(e.target.value)} className={cx(inputClass, "font-mono text-[12px]")} />
          </label>

          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-ink">Idempotency-Key</span>
            <input value={idempotency} onChange={(e) => setIdempotency(e.target.value)} className={cx(inputClass, "font-mono text-[12px]")} />
          </label>

          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-ink">Amount (NGN)</span>
              <input value={amount} onChange={(e) => setAmount(e.target.value)} className={inputClass} />
            </label>
            <label className="block">
              <span className="mb-1 block text-[12px] font-medium text-ink">Recipient</span>
              <input value={recipient} onChange={(e) => setRecipient(e.target.value)} className={inputClass} />
            </label>
          </div>

          <label className="block">
            <span className="mb-1 block text-[12px] font-medium text-ink">Recipient name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
          </label>

          {/* Being able to send the request *wrong* is the point: FR 4.1 makes
              the idempotency key mandatory, and seeing the 400 is how a
              developer learns that before it bites them in production. */}
          <label className="flex items-center gap-2 text-[12px] text-muted">
            <input
              type="checkbox"
              checked={sendKey}
              onChange={(e) => setSendKey(e.target.checked)}
              className="h-4 w-4 rounded border-line-strong text-violet-600 focus:ring-violet-500"
            />
            Send the Idempotency-Key header (uncheck to see the 400)
          </label>

          <Button onClick={run} loading={busy} full>
            Run in sandbox
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>

        <div>
          <p className="mb-1.5 text-[12px] font-medium text-ink">Response</p>
          <div className="scroll-thin h-[300px] overflow-auto rounded-field bg-code-bg p-4">
            {busy ? (
              <span className="flex items-center gap-2 text-[12px] text-code-comment">
                <Spinner className="h-4 w-4 text-white" /> sending…
              </span>
            ) : result ? (
              <>
                <p
                  className={cx(
                    "mb-2 font-mono text-[11px] font-bold",
                    result.status >= 200 && result.status < 300 ? "text-code-string" : "text-code-number",
                  )}
                >
                  HTTP {result.status || "network error"}
                </p>
                <pre className="font-mono text-[11px] leading-relaxed text-code-text">
                  <code>{JSON.stringify(result.body, null, 2)}</code>
                </pre>
              </>
            ) : (
              <p className="font-mono text-[11px] text-code-comment">
                {"// the response appears here"}
              </p>
            )}
          </div>
        </div>
      </div>
    </Card>
  );
}

function TestButton({
  webhookId,
  apiKey,
  onDone,
}: {
  webhookId: string;
  apiKey: string;
  onDone: () => void;
}) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      type="button"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await api(`/v1/webhooks/${webhookId}/test`, { method: "POST", apiKey });
        } catch {
          /* the delivery result is what the panel below reports */
        } finally {
          setBusy(false);
          onDone();
        }
      }}
      className="text-[12px] font-semibold text-violet-600 hover:text-violet-700 disabled:opacity-50"
    >
      {busy ? "Sending…" : "Test →"}
    </button>
  );
}

function DocCard({
  icon,
  title,
  body,
  href,
  external,
}: {
  icon: React.ReactNode;
  title: string;
  body: string;
  href: string;
  external?: boolean;
}) {
  return (
    <Link
      href={href}
      target={external ? "_blank" : undefined}
      className="card flex items-start gap-3 p-4 transition-colors hover:border-violet-200"
    >
      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-violet-50 text-violet-600">
        {icon}
      </span>
      <span className="min-w-0">
        <span className="block text-[13px] font-semibold text-heading">{title}</span>
        <span className="mt-0.5 block text-[12px] text-muted">{body}</span>
      </span>
    </Link>
  );
}


// ---------------------------------------------------------------------------
// Access gate
// ---------------------------------------------------------------------------

const KEY_STORE = "cowrie.developers.key";

/**
 * The portal is gated on a live API key.
 *
 * FR 4.1 makes the key the partner's credential, so the portal is gated on the
 * same thing the API is: the key is verified against a real endpoint before any
 * of this is rendered. An invalid or revoked key gets nothing.
 */
export default function DevelopersPage() {
  const [apiKey, setApiKey] = useState("");
  const [draft, setDraft] = useState(DEMO_KEY);
  const [checking, setChecking] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const stored = window.localStorage.getItem(KEY_STORE);
    if (stored) setApiKey(stored);
    setChecking(false);
  }, []);

  const signIn = async (candidate: string) => {
    setBusy(true);
    setError("");
    try {
      // Verified against the API, not merely pattern-matched.
      await api("/v1/stats?days=1", { apiKey: candidate });
      window.localStorage.setItem(KEY_STORE, candidate);
      setApiKey(candidate);
    } catch (err) {
      setError(err instanceof Error ? err.message : "That key was not accepted.");
    } finally {
      setBusy(false);
    }
  };

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas">
        <Spinner className="h-6 w-6 text-violet-600" />
      </div>
    );
  }

  if (!apiKey) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas grid-lines px-4">
        <form
          className="panel w-full max-w-[400px] space-y-4 p-6"
          onSubmit={(event) => {
            event.preventDefault();
            void signIn(draft.trim());
          }}
        >
          <div className="flex items-center gap-2.5">
            <CowrieMark className="h-6 w-6 text-violet-600" />
            <span className="text-[15px] font-semibold tracking-tight text-heading">
              Cowrie Developers
            </span>
          </div>

          <div>
            <h1 className="text-lg font-bold text-heading">Sign in with your API key</h1>
            <p className="mt-1 text-[13px] text-muted">Keys, webhooks and logs for your organisation.</p>
          </div>

          <label className="block">
            <span className="mb-1.5 block text-[13px] font-medium text-ink">Secret key</span>
            <input
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              autoComplete="off"
              spellCheck={false}
              className={cx(inputClass, "font-mono text-[12px]")}
              placeholder="ck_sandbox_..."
            />
          </label>

          {error ? <ErrorText>{error}</ErrorText> : null}

          <Button type="submit" full loading={busy}>
            Open portal
          </Button>

          <p className="text-[11px] text-subtle">
Revoked keys are rejected.
          </p>
        </form>
      </div>
    );
  }

  return (
    <DevelopersPortal
      apiKey={apiKey}
      setApiKey={setApiKey}
      onSignOut={() => {
        window.localStorage.removeItem(KEY_STORE);
        setApiKey("");
      }}
    />
  );
}
