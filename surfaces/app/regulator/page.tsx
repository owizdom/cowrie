"use client";
/**
 * Regulator portal (SRS 2.3, surface 5) — read-only audit and export.
 * Read-only is structural: no write route accepts the regulator token audience.
 */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { CowrieMark } from "@/components/brand";
import { Book, Download, ShieldCheck } from "@/components/icons";
import { Badge, Button, Card, CardHeader, ErrorText, Notice, Skeleton, cx, inputClass } from "@/components/ui";
import { api, clearToken, getToken, setToken } from "@/lib/api";
import { groupDigits, relativeTime, truncateHash } from "@/lib/format";

const REGULATORS = [
  { code: "SEC_NIGERIA", name: "SEC Nigeria", codeHint: "sec-ng-demo" },
  { code: "CMA_KENYA", name: "CMA Kenya", codeHint: "cma-ke-demo" },
  { code: "CBN", name: "Central Bank of Nigeria", codeHint: "cbn-demo" },
];

export default function RegulatorPage() {
  const [signedIn, setSignedIn] = useState(false);
  const [regulator, setRegulator] = useState("SEC_NIGERIA");
  const [accessCode, setAccessCode] = useState("sec-ng-demo");
  const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const [profile, setProfile] = useState<{ name?: string; interest?: string } | null>(null);
  const [reserve, setReserve] = useState<{ cusdcSupply: string; usdReserve: string; coveragePercent: string; isFullyBacked: boolean } | null>(null);
  const [audit, setAudit] = useState<{ chain: { valid: boolean; entriesChecked: number; brokenAtSeq: number | null } } | null>(null);
  const [summary, setSummary] = useState<{ total: number; settled: number; refunded: number; failed: number; volumeUsd: string } | null>(null);

  useEffect(() => { setSignedIn(Boolean(getToken("regulator"))); }, []);

  const load = useCallback(async () => {
    const [p, r, a, t] = await Promise.allSettled([
      api<{ name: string; interest: string }>("/regulator/profile", { audience: "regulator" }),
      api<{ cusdcSupply: string; usdReserve: string; coveragePercent: string; isFullyBacked: boolean }>("/regulator/reserve", { audience: "regulator" }),
      api<{ chain: { valid: boolean; entriesChecked: number; brokenAtSeq: number | null } }>("/regulator/audit", { audience: "regulator" }),
      api<{ summary: { total: number; settled: number; refunded: number; failed: number; volumeUsd: string } }>("/regulator/transactions?days=30", { audience: "regulator" }),
    ]);
    if (p.status === "fulfilled") setProfile(p.value);
    if (r.status === "fulfilled") setReserve(r.value);
    if (a.status === "fulfilled") setAudit(a.value);
    if (t.status === "fulfilled") setSummary(t.value.summary);
  }, []);

  useEffect(() => { if (signedIn) void load(); }, [signedIn, load]);

  if (!signedIn) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas grid-lines px-4">
        <form className="panel w-full max-w-[380px] space-y-4 p-6" onSubmit={async (e) => {
          e.preventDefault(); setBusy(true); setError("");
          try {
            const result = await api<{ token: string }>("/auth/regulator/login", { method: "POST", body: { regulator, accessCode } });
            setToken("regulator", result.token); setSignedIn(true);
          } catch (err) { setError(err instanceof Error ? err.message : "Invalid access code."); setBusy(false); }
        }}>
          <div className="flex items-center gap-2.5"><CowrieMark className="h-6 w-6 text-violet-600" /><span className="text-[15px] font-semibold text-heading">Cowrie Regulator Portal</span></div>
          <p className="text-[13px] text-muted">Read-only access.</p>
          <label className="block"><span className="mb-1 block text-[13px] font-medium text-ink">Regulator</span>
            <select value={regulator} onChange={(e) => { setRegulator(e.target.value); setAccessCode(REGULATORS.find((r) => r.code === e.target.value)?.codeHint ?? ""); }} className={inputClass}>
              {REGULATORS.map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}
            </select></label>
          <label className="block"><span className="mb-1 block text-[13px] font-medium text-ink">Access code</span>
            <input value={accessCode} onChange={(e) => setAccessCode(e.target.value)} className={cx(inputClass, "font-mono")} /></label>
          {error ? <ErrorText>{error}</ErrorText> : null}
          <Button type="submit" full loading={busy}>Sign in</Button>
          <Link href="/regulator/guide" className="block text-center text-[12px] font-semibold text-violet-600">Read the integration guide first →</Link>
        </form>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-canvas">
      <header className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-5 py-4">
          <div className="flex items-center gap-2.5"><CowrieMark className="h-6 w-6 text-violet-600" />
            <span className="text-[15px] font-semibold text-heading">Regulator Portal</span>
            <Badge tone="neutral">read-only</Badge></div>
          <div className="flex items-center gap-3">
            <Link href="/regulator/guide" className="text-[13px] font-semibold text-violet-600">Guide</Link>
            <Button size="sm" variant="ghost" onClick={() => { clearToken("regulator"); setSignedIn(false); }}>Sign out</Button>
          </div>
        </div>
      </header>

      <main id="main" className="mx-auto max-w-5xl space-y-4 px-5 py-8">
        <div><h1 className="text-xl font-bold tracking-tight text-heading">{profile?.name ?? "Regulator"}</h1>
          <p className="mt-1 text-[13px] text-muted">{profile?.interest ?? ""}</p></div>

        <div className="grid gap-4 sm:grid-cols-4">
          <Stat label="Transfers (30d)" value={summary ? String(summary.total) : null} />
          <Stat label="Settled" value={summary ? String(summary.settled) : null} />
          <Stat label="Refunded / failed" value={summary ? `${summary.refunded} / ${summary.failed}` : null} />
          <Stat label="Volume (USD)" value={summary ? `$${groupDigits(summary.volumeUsd).whole}` : null} />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Card className="p-5">
            <h2 className="text-[15px] font-semibold text-heading">cUSDC reserve position</h2>
            {reserve ? (
              <dl className="mt-3 space-y-2 text-[13px]">
                <div className="flex justify-between"><dt className="text-muted">On-chain supply</dt><dd className="font-semibold tabular-nums text-ink">{groupDigits(reserve.cusdcSupply).whole}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">USD reserves</dt><dd className="font-semibold tabular-nums text-ink">${groupDigits(reserve.usdReserve).whole}</dd></div>
                <div className="flex justify-between"><dt className="text-muted">Coverage</dt><dd className={cx("font-bold tabular-nums", reserve.isFullyBacked ? "text-success" : "text-danger")}>{reserve.coveragePercent}%</dd></div>
              </dl>
            ) : <Skeleton className="mt-3 h-20 w-full" />}
          </Card>

          <Card className="p-5">
            <h2 className="flex items-center gap-2 text-[15px] font-semibold text-heading"><ShieldCheck className="h-4 w-4 text-violet-600" />Audit integrity</h2>
            {audit ? (
              <>
                <p className={cx("mt-3 text-[19px] font-bold", audit.chain.valid ? "text-success" : "text-danger")}>
                  {audit.chain.valid ? "Verified" : `Broken at #${audit.chain.brokenAtSeq}`}
                </p>
                <p className="mt-1 text-[12px] text-muted">{audit.chain.entriesChecked} entries checked against their hash chain.</p>
              </>
            ) : <Skeleton className="mt-3 h-16 w-full" />}
          </Card>
        </div>



        <Card className="p-5">
          <p className="flex items-center gap-2 text-[13px] text-muted"><Book className="h-4 w-4 text-violet-600" />
            Signed period reports are generated by a Cowrie compliance officer and appear in
            <Link href="/admin/audit" className="ml-1 font-semibold text-violet-600">the export register</Link>.
          </p>
        </Card>
      </main>
    </div>
  );
}
function Stat({ label, value }: { label: string; value: string | null }) {
  return <Card className="p-4"><p className="text-[11px] uppercase tracking-wide text-subtle">{label}</p>
    {value === null ? <Skeleton className="mt-1.5 h-6 w-20" /> : <p className="mt-1 text-[19px] font-bold tabular-nums text-heading">{value}</p>}</Card>;
}
