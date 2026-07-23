"use client";
/**
 * Admin — KYC review queue (FR 5.2, SRS 3.1).
 *
 * SRS 3.1: "Side-by-side view of documents and liveness checks, with provider
 * confidence score included." The layout is exactly that: the submission on the
 * left, the decision panel on the right, so a reviewer never loses sight of what
 * they are deciding about while they decide it.
 */
import { useCallback, useEffect, useState } from "react";
import { Camera, Check, IdCard, ShieldCheck } from "@/components/icons";
import { Avatar, Badge, Button, Card, CardHeader, Chip, EmptyState, ErrorText, Notice, Skeleton, cx, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import { avatarTone, initials, relativeTime } from "@/lib/format";

type Submission = {
  id: string; status: string; idType: string; idTail: string; confidenceScore: number;
  livenessPassed: boolean; requestedLevel: string; createdAt: string; decidedBy: string;
  rejectionReason: string; provider: string;
  user: { id: string; fullName: string; phone: string; country: string; kycLevel: string; isFrozen: boolean } | null;
};

const FILTERS = [
  { key: "PENDING", label: "Pending" },
  { key: "", label: "All" },
  { key: "APPROVED", label: "Approved" },
  { key: "REJECTED", label: "Rejected" },
];

export default function KycQueuePage() {
  const [rows, setRows] = useState<Submission[] | null>(null);
  const [filter, setFilter] = useState("PENDING");
  const [selected, setSelected] = useState<Submission | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const q = filter ? `?status=${filter}` : "";
      const data = await api<{ submissions: Submission[] }>(`/admin/kyc${q}`, { audience: "admin" });
      setRows(data.submissions);
      setSelected((current) => data.submissions.find((s) => s.id === current?.id) ?? data.submissions[0] ?? null);
    } catch { setRows([]); }
  }, [filter]);

  useEffect(() => { void load(); }, [load]);

  const decide = async (decision: string) => {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      await api(`/admin/kyc/${selected.id}/decide`, { method: "POST", audience: "admin", body: { decision, reason } });
      setReason(""); await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Could not record that decision."); }
    finally { setBusy(false); }
  };

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-heading">KYC review queue</h1>
        <p className="mt-1 text-[13px] text-muted">Every decision is logged.</p>
      </div>

      <div className="flex flex-wrap gap-2">
        {FILTERS.map((f) => <Chip key={f.label} pressed={filter === f.key} onClick={() => setFilter(f.key)}>{f.label}</Chip>)}
      </div>

      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        {/* queue */}
        <Card className="self-start">
          <CardHeader title="Submissions" action={rows ? <Badge tone="warning">{rows.length}</Badge> : null} />
          <ul className="mt-3 divide-y divide-line border-t border-line">
            {rows === null ? <li className="p-4"><Skeleton className="h-12 w-full" /></li>
             : rows.length === 0 ? <li><EmptyState title="Nothing to review" icon={<Check className="h-6 w-6" />} /></li>
             : rows.map((row) => (
              <li key={row.id}>
                <button type="button" onClick={() => setSelected(row)} aria-current={selected?.id === row.id}
                  className={cx("flex w-full items-center gap-3 px-4 py-3 text-left transition-colors", selected?.id === row.id ? "bg-violet-50" : "hover:bg-raised")}>
                  <Avatar name={initials(row.user?.fullName ?? "?")} tone={avatarTone(row.id)} size="sm" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[13px] font-semibold text-heading">{row.user?.fullName ?? "Unknown"}</span>
                    <span className="block truncate text-[11px] text-muted">{row.idType.replace("_", " ")} · {relativeTime(row.createdAt)}</span>
                  </span>
                  <ConfidenceDot score={row.confidenceScore} />
                </button>
              </li>
            ))}
          </ul>
        </Card>

        {/* side-by-side review */}
        {selected ? (
          <Card>
            <CardHeader
              title={selected.user?.fullName ?? "Submission"}
              subtitle={`${selected.provider} · submitted ${relativeTime(selected.createdAt)}`}
              action={<Badge tone={selected.status === "APPROVED" ? "success" : selected.status === "REJECTED" ? "danger" : selected.status === "FROZEN" ? "warning" : "progress"}>{selected.status}</Badge>}
            />

            {/* documents and liveness, side by side */}
            <div className="grid gap-4 p-5 pt-4 sm:grid-cols-2">
              <Panel icon={<IdCard className="h-4 w-4" />} title="Identity document">
                <dl className="space-y-2 text-[13px]">
                  <Row label="Type" value={selected.idType.replace("_", " ")} />
                  <Row label="Number" value={`•••• ${selected.idTail}`} />
                  <Row label="Country" value={selected.user?.country ?? "—"} />
                  <Row label="Unlocks" value={selected.requestedLevel} />
                </dl>

              </Panel>

              <Panel icon={<Camera className="h-4 w-4" />} title="Liveness & match">
                <div className="flex items-baseline gap-2">
                  <span className={cx("text-[28px] font-bold tabular-nums", selected.confidenceScore >= 92 ? "text-success" : selected.confidenceScore >= 85 ? "text-warning" : "text-danger")}>
                    {(selected.confidenceScore / 100).toFixed(2)}
                  </span>
                  <span className="text-[12px] text-muted">provider confidence</span>
                </div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-line">
                  <div className={cx("h-full rounded-full", selected.confidenceScore >= 92 ? "bg-success" : selected.confidenceScore >= 85 ? "bg-warning" : "bg-danger")} style={{ width: `${selected.confidenceScore}%` }} />
                </div>
                <p className={cx("mt-3 inline-flex items-center gap-1.5 text-[13px] font-medium", selected.livenessPassed ? "text-success" : "text-danger")}>
                  <ShieldCheck className="h-4 w-4" />
                  {selected.livenessPassed ? "Liveness passed" : "Liveness failed"}
                </p>
              </Panel>
            </div>

            {selected.status === "PENDING" ? (
              <div className="border-t border-line p-5">
                <label htmlFor="reason" className="mb-1.5 block text-[13px] font-medium text-ink">Reason (required to reject or freeze)</label>
                <input id="reason" value={reason} onChange={(e) => setReason(e.target.value)} className={inputClass} placeholder="e.g. document image too blurred to match the selfie" />
                {error ? <div className="mt-2"><ErrorText>{error}</ErrorText></div> : null}
                <div className="mt-3 flex flex-wrap gap-2">
                  <Button loading={busy} onClick={() => decide("APPROVE")}>Approve</Button>
                  <Button variant="outline" loading={busy} disabled={!reason} onClick={() => decide("REJECT")}>Reject</Button>
                  <Button variant="danger" loading={busy} disabled={!reason} onClick={() => decide("FREEZE")}>Freeze account</Button>
                </div>

              </div>
            ) : (
              <div className="border-t border-line p-5">
                <Notice tone="neutral">
                  Decided by {selected.decidedBy || "—"}. {selected.rejectionReason}
                </Notice>
              </div>
            )}
          </Card>
        ) : null}
      </div>
    </div>
  );
}

function Panel({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-field border border-line p-4">
      <p className="flex items-center gap-2 text-[13px] font-semibold text-heading"><span className="text-violet-600">{icon}</span>{title}</p>
      <div className="mt-3">{children}</div>
    </div>
  );
}
function Row({ label, value }: { label: string; value: string }) {
  return <div className="flex justify-between gap-3"><dt className="text-muted">{label}</dt><dd className="font-medium text-ink">{value}</dd></div>;
}
function ConfidenceDot({ score }: { score: number }) {
  return <span className={cx("shrink-0 rounded-pill px-1.5 py-0.5 text-[10px] font-bold tabular-nums", score >= 92 ? "bg-success-bg text-success" : score >= 85 ? "bg-warning-bg text-warning" : "bg-danger-bg text-danger")}>{(score / 100).toFixed(2)}</span>;
}
