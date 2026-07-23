"use client";
/**
 * Developers — Try it (SRS 3.1 "interactive Try It console" + Python/TypeScript examples).
 * Sends a live request; the panel prints the actual response.
 */
import { useMemo, useState } from "react";
import { Button, Card, CopyButton, Spinner, cx, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import { usePortal } from "../portal-context";

const LANGS = ["Python", "TypeScript", "cURL"] as const;
type Lang = (typeof LANGS)[number];

export default function TryPage() {
  const { apiKey } = usePortal();
  const [amount, setAmount] = useState("80000");
  const [recipient, setRecipient] = useState("+254712345678");
  const [name, setName] = useState("Mary Wanjiru");
  const [lang, setLang] = useState<Lang>("Python");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ status: number; body: unknown } | null>(null);

  const snippets: Record<Lang, string> = useMemo(() => ({
    Python: `import requests

r = requests.post(
    "https://api.cowrie.africa/v1/payment_intents",
    headers={"X-API-Key": "${apiKey.slice(0, 18)}...", "Idempotency-Key": "ord_18934"},
    json={
        "sourceCurrency": "NGN",
        "destinationCurrency": "KES",
        "amount": "${amount}",
        "recipientName": "${name}",
        "recipientMsisdn": "${recipient}",
    },
)
print(r.json()["status"])`,
    TypeScript: `const r = await fetch("https://api.cowrie.africa/v1/payment_intents", {
  method: "POST",
  headers: {
    "X-API-Key": "${apiKey.slice(0, 18)}...",
    "Idempotency-Key": "ord_18934",
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    sourceCurrency: "NGN",
    destinationCurrency: "KES",
    amount: "${amount}",
    recipientName: "${name}",
    recipientMsisdn: "${recipient}",
  }),
});

const payment = await r.json();`,
    cURL: `curl -X POST https://api.cowrie.africa/v1/payment_intents \\
  -H "X-API-Key: ${apiKey.slice(0, 18)}..." \\
  -H "Idempotency-Key: ord_18934" \\
  -H "Content-Type: application/json" \\
  -d '{"sourceCurrency":"NGN","destinationCurrency":"KES","amount":"${amount}","recipientName":"${name}","recipientMsisdn":"${recipient}"}'`,
  }), [apiKey, amount, name, recipient]);

  const run = async () => {
    setBusy(true); setResult(null);
    try {
      const body = await api<unknown>("/v1/payment_intents", {
        method: "POST", apiKey,
        headers: { "Idempotency-Key": `try_${Date.now()}` },
        body: { sourceCurrency: "NGN", destinationCurrency: "KES", amount, recipientName: name, recipientMsisdn: recipient },
      });
      setResult({ status: 201, body });
    } catch (err) {
      const e = err as { status?: number; body?: unknown };
      setResult({ status: e.status ?? 0, body: e.body ?? String(err) });
    } finally { setBusy(false); }
  };

  return (
    <div className="p-6 lg:p-8">
      <h1 className="text-xl font-bold tracking-tight text-heading">Try it</h1>
      <p className="mt-1 font-mono text-[12px] text-muted">POST /v1/payment_intents</p>

      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <label className="block">
              <span className="mb-1 block text-[12px] text-muted">Amount (NGN)</span>
              <input value={amount} onChange={(e) => setAmount(e.target.value)} className={cx(inputClass, "tabular-nums")} />
            </label>
            <label className="block">
              <span className="mb-1 block text-[12px] text-muted">Recipient</span>
              <input value={recipient} onChange={(e) => setRecipient(e.target.value)} className={inputClass} />
            </label>
          </div>
          <label className="block">
            <span className="mb-1 block text-[12px] text-muted">Name</span>
            <input value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
          </label>
          <Button onClick={run} loading={busy} full>Send request</Button>
        </div>

        <div className="scroll-thin h-[260px] overflow-auto rounded-field bg-code-bg p-4">
          {busy ? (
            <span className="flex items-center gap-2 text-[12px] text-code-comment"><Spinner className="h-4 w-4 text-white" /> sending…</span>
          ) : result ? (
            <>
              <p className={cx("mb-2 font-mono text-[11px] font-bold", result.status >= 200 && result.status < 300 ? "text-code-string" : "text-code-number")}>
                HTTP {result.status || "error"}
              </p>
              <pre className="font-mono text-[11px] leading-relaxed text-code-text"><code>{JSON.stringify(result.body, null, 2)}</code></pre>
            </>
          ) : (
            <p className="font-mono text-[11px] text-code-comment">{"// response"}</p>
          )}
        </div>
      </div>

      <div className="mt-10">
        <div className="flex items-center justify-between">
          <div className="flex gap-1 rounded-lg bg-canvas p-0.5">
            {LANGS.map((l) => (
              <button key={l} type="button" onClick={() => setLang(l)}
                className={cx("rounded-md px-2.5 py-1 text-[12px] font-medium", lang === l ? "bg-white text-heading shadow-card" : "text-muted")}>
                {l}
              </button>
            ))}
          </div>
          <CopyButton value={snippets[lang]} label="code" />
        </div>
        <pre className="scroll-thin mt-3 overflow-x-auto rounded-field bg-code-bg p-4 font-mono text-[11.5px] leading-relaxed text-code-text">
          <code>{snippets[lang]}</code>
        </pre>
      </div>
    </div>
  );
}
