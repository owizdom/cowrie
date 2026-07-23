"use client";
/**
 * Admin — cUSDC reserves (FR 3.2, FR 5.3, SRS 3.1).
 * "Display of live supply and attestation history with minting and burning process."
 */
import { useCallback, useEffect, useState } from "react";
import { AreaChart, Badge, Button, Card, CardHeader, CopyButton, ErrorText, Notice, Skeleton, cx, inputClass } from "@/components/ui";
import { api } from "@/lib/api";
import { groupDigits, relativeTime, truncateHash } from "@/lib/format";

type Reserve = {
  cusdcSupply: string; usdReserve: string; coveragePercent: string; isFullyBacked: boolean;
  bankingPartner: string; attestor: string;
  totals: { minted: string; burned: string };
  movements: Array<{ id: string; kind: string; amount: string; reference: string; txHash: string; performedBy: string; approvals: string; createdAt: string }>;
  attestations: Array<{ id: string; date: string; coveragePercent: string; attestor: string; anchorTxHash: string; isFullyBacked: boolean }>;
};

export default function ReservePage() {
  const [data, setData] = useState<Reserve | null>(null);
  const [amount, setAmount] = useState("50000");
  const [reference, setReference] = useState("WIRE-IN-8823A1");
  const [approvals, setApprovals] = useState(3);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [ok, setOk] = useState("");

  const load = useCallback(async () => {
    try { setData(await api<Reserve>("/admin/reserve", { audience: "admin" })); } catch { setData(null); }
  }, []);
  useEffect(() => { void load(); }, [load]);

  const act = async (kind: "mint" | "burn" | "attest") => {
    setBusy(kind); setError(""); setOk("");
    try {
      const body = kind === "mint" ? { amount, usdDepositReference: reference, approvals }
        : kind === "burn" ? { amount, approvals } : {};
      await api(`/admin/reserve/${kind}`, { method: "POST", audience: "admin", body });
      setOk(kind === "attest" ? "Attestation published and anchored on-chain." : `${kind === "mint" ? "Minted" : "Burned"} ${amount} cUSDC.`);
      await load();
    } catch (err) { setError(err instanceof Error ? err.message : "That operation was refused."); }
    finally { setBusy(""); }
  };

  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div>
        <h1 className="text-xl font-bold tracking-tight text-heading">cUSDC reserves</h1>
        <p className="mt-1 text-[13px] text-muted">Gated on a confirmed deposit and 3-of-5 signatures.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-4">
        <Figure label="On-chain supply" value={data ? groupDigits(data.cusdcSupply).whole : null} suffix="cUSDC" />
        <Figure label="USD reserves" value={data ? `$${groupDigits(data.usdReserve).whole}` : null} />
        <Figure label="Coverage" value={data ? `${data.coveragePercent}%` : null} ok={data?.isFullyBacked} />
        <Figure label="Minted / burned" value={data ? `${groupDigits(data.totals.minted).whole} / ${groupDigits(data.totals.burned).whole}` : null} />
      </div>

      <Card className="p-5">
        <AreaChart points={[8.2, 8.6, 9.1, 9.4, 10.0, 10.6, 11.1, 11.6, 12.0, 12.2, 12.4]} />
        <div className="flex justify-between text-[10px] text-subtle"><span>30 days ago</span><span>Today</span></div>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <h2 className="text-[15px] font-semibold text-heading">Treasury operation</h2>
          <div className="mt-4 space-y-3">
            <label className="block"><span className="mb-1 block text-[12px] font-medium text-ink">Amount (cUSDC)</span>
              <input value={amount} onChange={(e) => setAmount(e.target.value)} className={cx(inputClass, "tabular-nums")} /></label>
            <label className="block"><span className="mb-1 block text-[12px] font-medium text-ink">USD deposit reference</span>
              <input value={reference} onChange={(e) => setReference(e.target.value)} className={cx(inputClass, "font-mono text-[12px]")} placeholder="clear this to see the refusal" /></label>
            <label className="block"><span className="mb-1 block text-[12px] font-medium text-ink">Treasury signatures held ({approvals} of 5)</span>
              <input type="range" min={1} max={5} value={approvals} onChange={(e) => setApprovals(Number(e.target.value))} className="w-full accent-violet-600" /></label>
            {approvals < 3 ? <p className="text-[12px] text-warning">Below the 3-of-5 threshold — the API will refuse.</p> : null}
            {error ? <ErrorText>{error}</ErrorText> : null}
            {ok ? <p className="text-[13px] font-medium text-success">{ok}</p> : null}
            <div className="flex flex-wrap gap-2">
              <Button loading={busy === "mint"} onClick={() => act("mint")}>Mint</Button>
              <Button variant="outline" loading={busy === "burn"} onClick={() => act("burn")}>Burn</Button>
              <Button variant="secondary" loading={busy === "attest"} onClick={() => act("attest")}>Publish attestation</Button>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader title="Mint & burn ledger" subtitle={data?.bankingPartner} />
          <ul className="mt-3 divide-y divide-line border-t border-line">
            {(data?.movements ?? []).slice(0, 8).map((m) => (
              <li key={m.id} className="flex items-center gap-3 px-5 py-2.5 text-[12px]">
                <span className="w-14 shrink-0 text-subtle">{relativeTime(m.createdAt)}</span>
                <Badge tone={m.kind === "MINT" ? "success" : "warning"}>{m.kind}</Badge>
                <span className="font-semibold tabular-nums text-heading">{groupDigits(m.amount).whole}</span>
                <span className="min-w-0 flex-1 truncate text-muted">{m.reference}</span>
                <span className="shrink-0 text-subtle">{m.approvals}</span>
              </li>
            ))}
            {!data ? <li className="p-4"><Skeleton className="h-10 w-full" /></li> : null}
          </ul>
        </Card>
      </div>

      <Card>
        <CardHeader title="Attestation history" subtitle={data?.attestor} />
        <div className="mt-3 table-scroll">
          <table className="w-full min-w-[520px] text-left text-[13px]">
            <thead><tr className="border-y border-line bg-raised text-[10px] uppercase tracking-wide text-subtle">
              <th className="px-5 py-2.5 font-semibold">Date</th><th className="px-5 py-2.5 font-semibold">Coverage</th><th className="px-5 py-2.5 font-semibold">Anchor</th></tr></thead>
            <tbody className="divide-y divide-line">
              {(data?.attestations ?? []).slice(0, 12).map((a) => (
                <tr key={a.id} className="hover:bg-raised">
                  <td className="px-5 py-2.5 text-muted">{new Date(a.date).toLocaleDateString(undefined, { month: "short", year: "numeric" })}</td>
                  <td className="px-5 py-2.5"><span className={cx("font-semibold tabular-nums", a.isFullyBacked ? "text-success" : "text-danger")}>{a.coveragePercent}%</span></td>
                  <td className="px-5 py-2.5"><span className="flex items-center gap-1.5"><code className="font-mono text-[11px]">{truncateHash(a.anchorTxHash, 8, 4)}</code><CopyButton value={a.anchorTxHash} label="anchor" /></span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function Figure({ label, value, suffix, ok }: { label: string; value: string | null; suffix?: string; ok?: boolean }) {
  return (
    <Card className="p-5">
      <p className="text-[11px] uppercase tracking-wide text-subtle">{label}</p>
      {value === null ? <Skeleton className="mt-2 h-7 w-24" /> : (
        <p className={cx("mt-1.5 text-[22px] font-bold tabular-nums", ok === true ? "text-success" : "text-heading")}>
          {value}{suffix ? <span className="ml-1 text-[11px] font-medium text-muted">{suffix}</span> : null}{ok === true ? " ✓" : ""}
        </p>
      )}
    </Card>
  );
}
