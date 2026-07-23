"use client";
/** Developers — overview. Volume, settlement and cost for this partner (FR 4, "Analyze transaction stats"). */
import { useEffect, useState } from "react";
import { Skeleton, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { groupDigits } from "@/lib/format";
import { usePortal } from "./portal-context";

type Stats = {
  counts: { created: number; settled: number; refunded: number; failed: number };
  volume: { sourceNgn: string; usdEquivalent: string };
  cost: { averageCostPercent: string };
  settlement: { successRate: number; medianSeconds: number };
};

export default function OverviewPage() {
  const { apiKey } = usePortal();
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    void (async () => {
      try { setStats(await api<Stats>("/v1/stats?days=30", { apiKey })); } catch { setStats(null); }
    })();
  }, [apiKey]);

  return (
    <div className="p-6 lg:p-8">
      <h1 className="text-xl font-bold tracking-tight text-heading">Overview</h1>
      <p className="mt-1 text-[13px] text-muted">Last 30 days</p>

      <dl className="mt-8 flex flex-wrap gap-x-14 gap-y-8">
        <Figure label="Payments" value={stats ? String(stats.counts.created) : null} />
        <Figure label="Settled" value={stats ? String(stats.counts.settled) : null} />
        <Figure label="Volume" value={stats ? `$${groupDigits(stats.volume.usdEquivalent).whole}` : null} />
        <Figure label="Average cost" value={stats ? `${stats.cost.averageCostPercent}%` : null} accent />
        <Figure label="Median settlement" value={stats ? `${stats.settlement.medianSeconds}s` : null} accent />
      </dl>

    </div>
  );
}

function Figure({ label, value, accent }: { label: string; value: string | null; accent?: boolean }) {
  return (
    <div>
      <dt className="text-[12px] text-subtle">{label}</dt>
      {value === null ? <Skeleton className="mt-1.5 h-7 w-20" /> : (
        <dd className={cx("mt-1 text-[26px] font-bold tabular-nums tracking-tight", accent ? "text-violet-600" : "text-heading")}>{value}</dd>
      )}
    </div>
  );
}
