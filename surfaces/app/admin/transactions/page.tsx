"use client";
/** Admin — full transaction register (FR 5.1), with the four SRS 3.1 filters. */
import { useCallback, useEffect, useState } from "react";
import { Badge, Card, Chip, EmptyState, Skeleton, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { groupDigits, money, relativeTime } from "@/lib/format";

type Row = { id: string; reference: string; state: string; createdAt: string; corridor: string; sourceAmount: string; destinationAmount: string; destinationCurrency: string; usdEquivalent: string; riskLevel: string; recipient: { name: string }; sender: { fullName: string } | null; mpesaReceipt: string; failureReason: string };

const STATES = ["", "SETTLED", "REFUNDED", "FAILED", "BRIDGING", "CANCELLED"];
const SIZES = [["", "Any size"], ["100", "≥ $100"], ["500", "≥ $500"], ["1000", "≥ $1k"]];
const RISKS = ["", "LOW", "MEDIUM", "HIGH"];

export default function TransactionsPage() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [state, setState] = useState(""); const [size, setSize] = useState(""); const [risk, setRisk] = useState(""); const [corridor, setCorridor] = useState("NGN->KES");

  const load = useCallback(async () => {
    const p = new URLSearchParams({ limit: "200" });
    if (state) p.set("state", state); if (size) p.set("minUsd", size); if (risk) p.set("risk", risk); if (corridor) p.set("corridor", corridor);
    try { setRows((await api<{ transactions: Row[] }>(`/admin/transactions?${p}`, { audience: "admin" })).transactions); } catch { setRows([]); }
  }, [state, size, risk, corridor]);
  useEffect(() => { void load(); }, [load]);

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div><h1 className="text-xl font-bold tracking-tight text-heading">Transactions</h1>
        <p className="mt-1 text-[13px] text-muted">{rows?.length ?? 0} matching · rule-based and velocity-based flags applied at authorisation.</p></div>

      <Card className="space-y-2 p-4">
        <Group label="Status">{STATES.map((s) => <Chip key={s || "all"} pressed={state === s} onClick={() => setState(s)}>{s || "All"}</Chip>)}</Group>
        <Group label="Corridor"><Chip tone="dark" pressed={corridor === "NGN->KES"} onClick={() => setCorridor("NGN->KES")}>NGN→KES</Chip><Chip tone="dark" pressed={corridor === ""} onClick={() => setCorridor("")}>All corridors</Chip></Group>
        <Group label="Size">{SIZES.map(([k, l]) => <Chip key={l} pressed={size === k} onClick={() => setSize(k)}>{l}</Chip>)}</Group>
        <Group label="Risk">{RISKS.map((r) => <Chip key={r || "any"} pressed={risk === r} onClick={() => setRisk(r)}>{r || "Any risk"}</Chip>)}</Group>
      </Card>

      <Card>
        <div className="table-scroll">
          <table className="w-full min-w-[860px] text-left text-[13px]">
            <thead><tr className="border-b border-line bg-raised text-[10px] uppercase tracking-wide text-subtle">
              {["Reference", "Time", "Sender", "Recipient", "Amount", "USD", "Status", "Risk"].map((h) => <th key={h} className="px-4 py-2.5 font-semibold">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-line">
              {rows === null ? <tr><td colSpan={8} className="p-4"><Skeleton className="h-8 w-full" /></td></tr>
               : rows.length === 0 ? <tr><td colSpan={8}><EmptyState title="Nothing matches these filters" /></td></tr>
               : rows.map((r) => (
                <tr key={r.id} className="hover:bg-raised">
                  <td className="px-4 py-2.5 font-mono text-[11px] text-muted">{r.reference}</td>
                  <td className="px-4 py-2.5 text-subtle">{relativeTime(r.createdAt)}</td>
                  <td className="px-4 py-2.5 max-w-[140px] truncate text-heading">{r.sender?.fullName ?? "—"}</td>
                  <td className="px-4 py-2.5 max-w-[140px] truncate text-heading">{r.recipient.name}</td>
                  <td className="whitespace-nowrap px-4 py-2.5 tabular-nums">
                    <span className="text-heading">{money(r.sourceAmount, "NGN", { decimals: false })}</span>
                    <span className="mx-1 text-subtle">→</span>
                    <span className="font-semibold text-violet-600">{r.destinationCurrency} {groupDigits(r.destinationAmount).whole}</span>
                  </td>
                  <td className="px-4 py-2.5 tabular-nums text-muted">${r.usdEquivalent}</td>
                  <td className="px-4 py-2.5"><Badge dot tone={r.state === "SETTLED" ? "success" : r.state === "REFUNDED" ? "warning" : r.state === "FAILED" || r.state === "CANCELLED" ? "danger" : "progress"}>{r.state}</Badge></td>
                  <td className="px-4 py-2.5"><Badge tone={r.riskLevel === "HIGH" ? "danger" : r.riskLevel === "MEDIUM" ? "warning" : "neutral"}>{r.riskLevel}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="flex items-center gap-2"><span className="w-14 shrink-0 text-[10px] font-semibold uppercase tracking-wide text-subtle">{label}</span><div className="flex flex-wrap gap-1.5">{children}</div></div>;
}
