"use client";
/** Developers — webhook endpoints and signature verification (FR 4.3). */
import { useCallback, useEffect, useState } from "react";
import { Badge, Card, CopyButton, EmptyState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import { usePortal } from "../portal-context";

type Hook = { id: string; url: string; events: string[]; status: string; createdAt: string };
type Delivery = { id: string; event: string; attempt: number; responseStatus: number; delivered: boolean; createdAt: string };

export default function WebhooksPage() {
  const { apiKey } = usePortal();
  const [hooks, setHooks] = useState<Hook[] | null>(null);
  const [deliveries, setDeliveries] = useState<Delivery[]>([]);
  const [busy, setBusy] = useState("");

  const load = useCallback(async () => {
    const [h, d] = await Promise.allSettled([
      api<{ data: Hook[] }>("/v1/webhooks", { apiKey }),
      api<{ data: Delivery[] }>("/v1/webhooks/deliveries?limit=8", { apiKey }),
    ]);
    setHooks(h.status === "fulfilled" ? h.value.data : []);
    if (d.status === "fulfilled") setDeliveries(d.value.data);
  }, [apiKey]);

  useEffect(() => { void load(); }, [load]);

  return (
    <div className="p-6 lg:p-8">
      <h1 className="text-xl font-bold tracking-tight text-heading">Webhooks</h1>
      <p className="mt-1 text-[13px] text-muted">HMAC-SHA256 over <code className="font-mono">{"{timestamp}.{body}"}</code></p>

      <Card className="mt-8 divide-y divide-line">
        {hooks === null ? <div className="p-5"><Skeleton className="h-8 w-full" /></div>
         : hooks.length === 0 ? <EmptyState title="No endpoints" />
         : hooks.map((h) => (
          <div key={h.id} className="flex flex-wrap items-center gap-3 px-5 py-4">
            <code className="min-w-0 flex-1 truncate font-mono text-[12px] text-ink">{h.url}</code>
            <span className="text-[12px] text-subtle">{h.events.length} events</span>
            <button type="button" disabled={busy === h.id}
              onClick={async () => { setBusy(h.id); try { await api(`/v1/webhooks/${h.id}/test`, { method: "POST", apiKey }); } catch {} finally { setBusy(""); void load(); } }}
              className="text-[12px] font-semibold text-violet-600 disabled:opacity-50">
              {busy === h.id ? "Sending…" : "Test"}
            </button>
          </div>
        ))}
      </Card>

      {deliveries.length > 0 ? (
        <>
          <h2 className="mt-10 text-[15px] font-semibold text-heading">Recent deliveries</h2>
          <ul className="mt-3 divide-y divide-line">
            {deliveries.map((d) => (
              <li key={d.id} className="flex items-center gap-3 py-2.5 text-[12px]">
                <span className="w-16 shrink-0 text-subtle">{relativeTime(d.createdAt)}</span>
                <code className="min-w-0 flex-1 truncate font-mono text-ink">{d.event}</code>
                <Badge tone={d.delivered ? "success" : "danger"}>{d.responseStatus || "no response"}</Badge>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}
