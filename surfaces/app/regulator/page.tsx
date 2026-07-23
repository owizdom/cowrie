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
  { code: "SEC_NIGERIA", name: "SEC Nigeria" },
  { code: "CMA_KENYA", name: "CMA Kenya" },
  { code: "CBN", name: "Central Bank of Nigeria" },
];

export default function RegulatorPage() {
  const [signedIn, setSignedIn] = useState(false);
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [regulator, setRegulator] = useState("SEC_NIGERIA");
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
      <div className="flex min-h-screen items-center justify-center bg-canvas px-4">
        <form
          className="w-full max-w-[360px] space-y-5"
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            setError("");
            try {
              const path = mode === "signin" ? "/auth/regulator/login" : "/auth/regulator/register";
              const body =
                mode === "signin"
                  ? { email, password }
                  : { fullName, email, password, regulator };
              const result = await api<{ token: string }>(path, { method: "POST", body });
              setToken("regulator", result.token);
              setSignedIn(true);
            } catch (err) {
              setError(err instanceof Error ? err.message : "Could not sign in.");
              setBusy(false);
            }
          }}
        >
          <div className="flex items-center gap-2">
            <CowrieMark className="h-6 w-6 text-violet-600" />
            <span className="text-[15px] font-semibold tracking-tight text-heading">
              Cowrie Regulator Portal
            </span>
          </div>

          <h1 className="text-lg font-bold text-heading">
            {mode === "signin" ? "Sign in" : "Request access"}
          </h1>

          {mode === "signup" ? (
            <>
              <label className="block">
                <span className="mb-1.5 block text-[13px] font-medium text-ink">Full name</span>
                <input value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" required minLength={2} className={inputClass} />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-[13px] font-medium text-ink">Regulator</span>
                <select value={regulator} onChange={(e) => setRegulator(e.target.value)} className={inputClass}>
                  {REGULATORS.map((r) => (
                    <option key={r.code} value={r.code}>{r.name}</option>
                  ))}
                </select>
              </label>
            </>
          ) : null}

          <label className="block">
            <span className="mb-1.5 block text-[13px] font-medium text-ink">Email</span>
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required className={inputClass} />
          </label>

          <label className="block">
            <span className="mb-1.5 block text-[13px] font-medium text-ink">Password</span>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === "signin" ? "current-password" : "new-password"}
              required
              minLength={8}
              className={inputClass}
            />
          </label>

          {error ? <ErrorText>{error}</ErrorText> : null}

          <Button type="submit" full loading={busy}>
            {mode === "signin" ? "Sign in" : "Create account"}
          </Button>

          <p className="text-center text-[13px] text-muted">
            {mode === "signin" ? "No account yet? " : "Already registered? "}
            <button
              type="button"
              onClick={() => { setMode(mode === "signin" ? "signup" : "signin"); setError(""); }}
              className="font-semibold text-violet-600"
            >
              {mode === "signin" ? "Request access" : "Sign in"}
            </button>
          </p>

          <Link href="/regulator/guide" className="block text-center text-[12px] text-subtle hover:text-muted">
            Integration guide
          </Link>
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
            <Button size="sm" variant="ghost" onClick={() => { clearToken("regulator"); window.location.href = "/"; }}>Sign out</Button>
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
