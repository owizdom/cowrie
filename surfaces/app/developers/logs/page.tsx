"use client";
/** Developers — payment log. */
import { useEffect, useState } from "react";
import { Badge, EmptyState, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { groupDigits, relativeTime } from "@/lib/format";
import { usePortal } from "../portal-context";

type Intent = { id: string; status: string; amount: string; reference: string; createdAt: string; recipient: { name: string } };

export default function LogsPage() {
  const { apiKey } = usePortal();
  const [rows, setRows] = useState<Intent[] | null>(null);

  useEffect(() => {
    void (async () => {
      try { setRows((await api<{ data: Intent[] }>("/v1/payment_intents?limit=50", { apiKey })).data); }
      catch { setRows([]); }
    })();
  }, [apiKey]);

  return (
    <div className="p-6 lg:p-8">
      <h1 className="text-xl font-bold tracking-tight text-heading">Payments</h1>

      {rows === null ? <Skeleton className="mt-8 h-32 w-full" />
       : rows.length === 0 ? <div className="mt-8"><EmptyState title="No payments yet">Send one from Try it.</EmptyState></div>
       : (
        <ul className="mt-8 divide-y divide-line">
          {rows.map((r) => (
            <li key={r.id} className="flex items-center gap-4 py-3 text-[13px]">
              <span className="w-16 shrink-0 text-subtle">{relativeTime(r.createdAt)}</span>
              <span className="min-w-0 flex-1 truncate text-heading">{r.recipient.name}</span>
              <span className="tabular-nums text-muted">₦{groupDigits(r.amount).whole}</span>
              <Badge tone={r.status === "SETTLED" ? "success" : r.status === "FAILED" ? "danger" : "progress"}>{r.status}</Badge>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
