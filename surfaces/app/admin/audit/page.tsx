"use client";
/**
 * Admin — audit log and regulator export (NFR 5, FR 5.3).
 * Verifying the chain is the demonstration: it reports the exact row if broken.
 */
import { useCallback, useEffect, useState } from "react";
import { Check, Download, ShieldCheck, Upload } from "@/components/icons";
import { Badge, Button, Card, CardHeader, CopyButton, ErrorText, Notice, Skeleton, cx } from "@/components/ui";
import { api, getToken } from "@/lib/api";
import { fullTimestamp, relativeTime, truncateHash } from "@/lib/format";

type Entry = { seq: number; entityType: string; entityId: string; action: string; actor: string; actorId: string; ts: string; entryHash: string; anchorTxHash: string };
type Verify = { valid: boolean; entriesChecked: number; brokenAtSeq: number | null; reason: string; headHash?: string };
type Export = { id: string; regulator: string; periodStart: string; periodEnd: string; rowCount: number; totalVolumeUsd: string; contentHash: string; signature: string; createdAt: string; downloadUrl: string };

export default function AuditPage() {
  const [entries, setEntries] = useState<Entry[] | null>(null);
  const [verify, setVerify] = useState<Verify | null>(null);
  const [exports, setExports] = useState<Export[]>([]);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    const [e, v, x] = await Promise.allSettled([
      api<{ entries: Entry[] }>("/admin/audit?limit=40", { audience: "admin" }),
      api<Verify>("/admin/audit/verify", { audience: "admin" }),
      api<{ exports: Export[] }>("/regulator/exports", { audience: "admin" }),
    ]);
    if (e.status === "fulfilled") setEntries(e.value.entries); else setEntries([]);
    if (v.status === "fulfilled") setVerify(v.value);
    if (x.status === "fulfilled") setExports(x.value.exports);
  }, []);
  useEffect(() => { void load(); }, [load]);

  const run = async (what: "anchor" | "export") => {
    setBusy(what); setError("");
    try {
      if (what === "anchor") await api("/admin/audit/anchor", { method: "POST", audience: "admin" });
      else await api("/regulator/exports?regulator=SEC_NIGERIA&days=30", { method: "POST", audience: "admin" });
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : "Refused."); }
    finally { setBusy(""); }
  };

  const download = async (url: string, name: string) => {
    const response = await fetch(`/api${url}`, { headers: { Authorization: `Bearer ${getToken("admin") ?? ""}` } });
    if (!response.ok) return;
    const blob = await response.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = href; a.download = name; a.click(); URL.revokeObjectURL(href);
  };

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-heading">Audit log & regulator export</h1>
        <p className="mt-1 text-[13px] text-muted">Append-only and hash-chained.</p>
      </div>

      {verify ? (
        <Card className={cx("p-5", verify.valid ? "border-success-ring bg-success-bg" : "border-danger-ring bg-danger-bg")}>
          <p className="flex items-center gap-2 text-[15px] font-semibold text-heading">
            <ShieldCheck className={cx("h-5 w-5", verify.valid ? "text-success" : "text-danger")} />
            {verify.valid ? "Chain verified" : `Chain broken at entry #${verify.brokenAtSeq}`}
          </p>
          <p className="mt-1 text-[13px] text-muted">
            {verify.entriesChecked} entries checked. {verify.reason || "Every entry matches its recorded hash and its predecessor."}
          </p>
          {verify.headHash ? (
            <p className="mt-2 flex items-center gap-1.5 text-[11px]">
              <span className="text-subtle">Head</span>
              <code className="font-mono text-ink">{truncateHash(verify.headHash, 10, 6)}</code>
              <CopyButton value={verify.headHash} label="head hash" />
            </p>
          ) : null}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => void load()}>Re-verify</Button>
            <Button size="sm" loading={busy === "anchor"} onClick={() => run("anchor")}>Anchor pending entries</Button>
          </div>
        </Card>
      ) : <Skeleton className="h-28 w-full rounded-card" />}

      {error ? <ErrorText>{error}</ErrorText> : null}

      <Card>
        <CardHeader title="Regulator exports" subtitle="Signed transaction reports for SEC Nigeria and CMA Kenya (FR 5.3)"
          action={<Button size="sm" loading={busy === "export"} onClick={() => run("export")}><Upload className="h-3.5 w-3.5" />Generate</Button>} />
        <ul className="mt-3 divide-y divide-line border-t border-line">
          {exports.length === 0 ? <li className="px-5 py-6 text-center text-[13px] text-muted">No exports yet.</li> : exports.slice(0, 5).map((x) => (
            <li key={x.id} className="flex flex-wrap items-center gap-3 px-5 py-3 text-[12px]">
              <Badge tone="progress">{x.regulator.replace("_", " ")}</Badge>
              <span className="text-muted">{x.rowCount} rows · ${Number(x.totalVolumeUsd).toLocaleString()}</span>
              <code className="font-mono text-[11px] text-subtle">{truncateHash(x.contentHash, 8, 4)}</code>
              <Badge tone="success">signed</Badge>
              <span className="ml-auto flex items-center gap-2">
                <span className="text-subtle">{relativeTime(x.createdAt)}</span>
                <button type="button" onClick={() => download(x.downloadUrl, `cowrie-${x.regulator}.csv`)} className="inline-flex items-center gap-1 font-semibold text-violet-600 hover:text-violet-700">
                  <Download className="h-3.5 w-3.5" />CSV
                </button>
              </span>
            </li>
          ))}
        </ul>

      </Card>

      <Card>
        <CardHeader title="Audit trail" subtitle="Most recent first" />
        <div className="mt-3 table-scroll">
          <table className="w-full min-w-[720px] text-left text-[12px]">
            <thead><tr className="border-y border-line bg-raised text-[10px] uppercase tracking-wide text-subtle">
              <th className="px-5 py-2.5 font-semibold">#</th><th className="px-5 py-2.5 font-semibold">Action</th><th className="px-5 py-2.5 font-semibold">Entity</th>
              <th className="px-5 py-2.5 font-semibold">Actor</th><th className="px-5 py-2.5 font-semibold">When</th><th className="px-5 py-2.5 font-semibold">Hash</th><th className="px-5 py-2.5 font-semibold">Anchor</th></tr></thead>
            <tbody className="divide-y divide-line">
              {entries === null ? <tr><td colSpan={7} className="p-4"><Skeleton className="h-8 w-full" /></td></tr> : entries.map((e) => (
                <tr key={e.seq} className="hover:bg-raised">
                  <td className="px-5 py-2 font-mono tabular-nums text-subtle">{e.seq}</td>
                  <td className="px-5 py-2 font-medium text-heading">{e.action}</td>
                  <td className="px-5 py-2 text-muted">{e.entityType}</td>
                  <td className="px-5 py-2"><Badge tone={e.actor === "ADMIN" ? "progress" : "neutral"}>{e.actor}</Badge></td>
                  <td className="px-5 py-2 text-subtle">{relativeTime(e.ts)}</td>
                  <td className="px-5 py-2"><code className="font-mono text-[10px] text-muted">{e.entryHash.slice(0, 10)}…</code></td>
                  <td className="px-5 py-2">{e.anchorTxHash ? <Check className="h-3.5 w-3.5 text-success" /> : <span className="text-subtle">—</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}
