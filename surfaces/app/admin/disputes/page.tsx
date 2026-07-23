"use client";
/** Admin — disputes (FR 5.2: approve, reject, freeze, escalate — all permanently logged). */
import { useCallback, useEffect, useState } from "react";
import { Badge, Button, Card, EmptyState, ErrorText, Skeleton, cx, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import { relativeTime } from "@/lib/format";

type Dispute = { id: string; subject: string; body: string; status: string; createdAt: string; resolution: string; resolvedBy: string; user: { fullName: string; phone: string } | null; transaction: { reference: string; state: string; amount: string } | null };

export default function DisputesPage() {
  const [rows, setRows] = useState<Dispute[] | null>(null);
  const [resolution, setResolution] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(""); const [error, setError] = useState("");

  const load = useCallback(async () => {
    try { setRows((await api<{ disputes: Dispute[] }>("/admin/disputes", { audience: "admin" })).disputes); } catch { setRows([]); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const decide = async (id: string, action: string) => {
    setBusy(id); setError("");
    try { await api(`/admin/disputes/${id}/decide`, { method: "POST", audience: "admin", body: { action, resolution: resolution[id] ?? "" } }); await load(); }
    catch (err) { setError(err instanceof Error ? err.message : "Refused."); } finally { setBusy(""); }
  };

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div><h1 className="text-xl font-bold tracking-tight text-heading">Disputes</h1>
        <p className="mt-1 text-[13px] text-muted">Officer role. Resolve, reject or escalate — every action is written to the audit log.</p></div>
      {error ? <ErrorText>{error}</ErrorText> : null}
      <div className="space-y-3">
        {rows === null ? <Skeleton className="h-32 w-full rounded-card" />
         : rows.length === 0 ? <Card><EmptyState title="No disputes open" /></Card>
         : rows.map((d) => (
          <Card key={d.id} className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="text-[15px] font-semibold text-heading">{d.subject}</p>
                <p className="mt-0.5 text-[12px] text-muted">{d.user?.fullName} · {d.user?.phone} · {relativeTime(d.createdAt)}</p>
              </div>
              <Badge tone={d.status === "RESOLVED" ? "success" : d.status === "ESCALATED" ? "warning" : d.status === "REJECTED" ? "danger" : "progress"}>{d.status}</Badge>
            </div>
            <p className="mt-3 text-[13px] leading-relaxed text-muted">{d.body}</p>
            {d.transaction ? <p className="mt-2 font-mono text-[11px] text-subtle">{d.transaction.reference} · {d.transaction.state} · ₦{Number(d.transaction.amount).toLocaleString()}</p> : null}
            {d.status === "OPEN" || d.status === "ESCALATED" ? (
              <div className="mt-4 space-y-2">
                <input value={resolution[d.id] ?? ""} onChange={(e) => setResolution((r) => ({ ...r, [d.id]: e.target.value }))} placeholder="Resolution note" className={inputClass} />
                <div className="flex flex-wrap gap-2">
                  <Button size="sm" loading={busy === d.id} onClick={() => decide(d.id, "RESOLVE")}>Resolve</Button>
                  <Button size="sm" variant="outline" loading={busy === d.id} onClick={() => decide(d.id, "ESCALATE")}>Escalate</Button>
                  <Button size="sm" variant="ghost" loading={busy === d.id} onClick={() => decide(d.id, "REJECT")}>Reject</Button>
                </div>
              </div>
            ) : d.resolution ? <p className="mt-3 rounded-field bg-canvas p-3 text-[12px] text-muted"><strong className="text-ink">{d.resolvedBy}:</strong> {d.resolution}</p> : null}
          </Card>
        ))}
      </div>
    </div>
  );
}
