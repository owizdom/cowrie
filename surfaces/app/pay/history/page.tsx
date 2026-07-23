"use client";

/**
 * CowriePay — history and statement export.
 *
 * SRS 2.2 lists both "check history" and "export statements" among the nine
 * CowriePay user functions.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ChevronLeft, Download } from "@/components/icons";
import { Avatar, Badge, Button, Card, EmptyState, Skeleton, cx } from "@/components/ui";
import { TabBar } from "@/components/pay/tab-bar";
import { useRequireSession } from "@/components/pay/session";
import { api, getToken, type Transfer } from "@/lib/api";
import { avatarTone, initials, money, relativeTime, STATE_PRESENTATION } from "@/lib/format";

export default function HistoryPage() {
  const { user, loading } = useRequireSession();
  const [transfers, setTransfers] = useState<Transfer[] | null>(null);
  const [summary, setSummary] = useState<Record<string, string> | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await api<{ transfers: Transfer[]; summary: Record<string, string> }>(
        "/transfers?limit=100",
        { audience: "cowriepay" },
      );
      setTransfers(result.transfers);
      setSummary(result.summary);
    } catch {
      setTransfers([]);
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  // The export is an authenticated download, so it cannot be a plain link —
  // the bearer token has to travel with the request.
  const exportStatement = async () => {
    const response = await fetch("/api/transfers/export/statement.csv", {
      headers: { Authorization: `Bearer ${getToken("cowriepay") ?? ""}` },
    });
    if (!response.ok) return;
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "cowrie-statement.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  };

  if (loading) return <Skeleton className="m-5 h-64" />;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin pb-4">
        <header className="flex items-center gap-2 px-5 pb-2 pt-3">
          <Link href="/pay" className="flex h-9 w-9 items-center justify-center rounded-full text-muted hover:bg-canvas" aria-label="Back to home">
            <ChevronLeft />
          </Link>
          <h1 className="text-[15px] font-semibold text-heading">History</h1>
        </header>

        {summary ? (
          <section className="px-5 pt-2">
            <Card className="grid grid-cols-3 divide-x divide-line p-4">
              <Stat label="Sent" value={money(summary.totalSentNgn, "NGN", { decimals: false })} />
              <Stat label="Received" value={`KES ${Number(summary.totalReceivedKes).toLocaleString()}`} />
              <Stat label="Fees" value={money(summary.totalFeesNgn, "NGN", { decimals: false })} />
            </Card>
          </section>
        ) : null}

        <div className="px-5 pt-3">
          <Button variant="outline" size="sm" onClick={exportStatement}>
            <Download className="h-3.5 w-3.5" />
            Export statement (CSV)
          </Button>
        </div>

        <ul className="mt-3 space-y-2 px-5">
          {transfers === null ? (
            <Skeleton className="h-20 w-full rounded-card" />
          ) : transfers.length === 0 ? (
            <EmptyState title="Nothing here yet">Your transfers will appear here.</EmptyState>
          ) : (
            transfers.map((t) => {
              const p = STATE_PRESENTATION[t.state];
              return (
                <li key={t.id}>
                  <Link href={`/pay/status/${t.id}`} className="flex items-center gap-3 rounded-card border border-line bg-white px-3.5 py-3 hover:border-line-strong">
                    <Avatar name={initials(t.recipient.name)} tone={avatarTone(t.recipient.msisdn || t.id)} size="sm" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold text-heading">{t.recipient.name}</p>
                      <p className="truncate text-[12px] text-muted">
                        {t.reference} · {relativeTime(t.createdAt)}
                      </p>
                    </div>
                    <div className="shrink-0 text-right">
                      <p className="text-sm font-semibold tabular-nums text-heading">
                        {money(t.source.amount, "NGN", { decimals: false })}
                      </p>
                      <Badge tone={p.tone} className="mt-1">{p.label}</Badge>
                    </div>
                  </Link>
                </li>
              );
            })
          )}
        </ul>
      </div>
      <TabBar />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="px-2 text-center">
      <p className="text-[10px] uppercase tracking-wide text-subtle">{label}</p>
      <p className="mt-1 text-[13px] font-bold tabular-nums text-heading">{value}</p>
    </div>
  );
}
