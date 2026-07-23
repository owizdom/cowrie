"use client";
/** Admin — sanctions watch (FR 1.3: OFAC, UN, EU at signup, per transfer, daily refresh). */
import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, CardHeader, Notice, Skeleton, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { relativeTime } from "@/lib/format";

type Screening = { id: string; trigger: string; passed: boolean; listsChecked: string[]; matchedName: string; matchScore: number; createdAt: string; user: { fullName: string; isFrozen: boolean } | null };

export default function SanctionsPage() {
  const [data, setData] = useState<{ screenings: Screening[]; summary: { total: number; hits: number; lists: string[] } } | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setData(await api("/admin/sanctions", { audience: "admin" })); } catch { setData(null); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div><h1 className="text-xl font-bold tracking-tight text-heading">Sanctions watch</h1>
        <p className="mt-1 text-[13px] text-muted">Screened at signup, per transfer, and daily.</p></div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card className="p-5"><p className="text-[11px] uppercase tracking-wide text-subtle">Screenings recorded</p><p className="mt-1.5 text-[22px] font-bold tabular-nums text-heading">{data?.summary.total ?? "—"}</p></Card>
        <Card className="p-5"><p className="text-[11px] uppercase tracking-wide text-subtle">Matches</p><p className={cx("mt-1.5 text-[22px] font-bold tabular-nums", data?.summary.hits ? "text-danger" : "text-heading")}>{data?.summary.hits ?? "—"}</p></Card>
        <Card className="p-5"><p className="text-[11px] uppercase tracking-wide text-subtle">Lists</p><p className="mt-1.5 text-[15px] font-semibold text-heading">{(data?.summary.lists ?? []).join(" · ")}</p></Card>
      </div>


      <Card>
        <CardHeader title="Recent screenings" action={
          <Button size="sm" variant="outline" loading={busy} onClick={async () => { setBusy(true); try { await api("/admin/sanctions/refresh", { method: "POST", audience: "admin" }); await load(); } finally { setBusy(false); } }}>
            Run daily refresh
          </Button>} />
        <div className="mt-3 table-scroll">
          <table className="w-full min-w-[640px] text-left text-[13px]">
            <thead><tr className="border-y border-line bg-raised text-[10px] uppercase tracking-wide text-subtle">
              {["When", "User", "Trigger", "Lists", "Result"].map((h) => <th key={h} className="px-5 py-2.5 font-semibold">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-line">
              {!data ? <tr><td colSpan={5} className="p-4"><Skeleton className="h-8 w-full" /></td></tr> : data.screenings.slice(0, 40).map((s) => (
                <tr key={s.id} className="hover:bg-raised">
                  <td className="px-5 py-2.5 text-subtle">{relativeTime(s.createdAt)}</td>
                  <td className="px-5 py-2.5 text-heading">{s.user?.fullName ?? "—"}{s.user?.isFrozen ? <Badge tone="danger" className="ml-2">frozen</Badge> : null}</td>
                  <td className="px-5 py-2.5 text-muted">{s.trigger}</td>
                  <td className="px-5 py-2.5 text-[11px] text-subtle">{(s.listsChecked ?? []).join(", ")}</td>
                  <td className="px-5 py-2.5">{s.passed ? <Badge tone="success" dot>Clear</Badge> : <Badge tone="danger" dot>{s.matchedName} · {s.matchScore}%</Badge>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
