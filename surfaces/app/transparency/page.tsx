"use client";

/**
 * Public transparency page (SRS 3.1).
 * Live supply · reserve · attestations · anchor proof · contract addresses.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { CowrieMark } from "@/components/brand";
import { CopyButton, Skeleton, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { groupDigits, relativeTime, truncateHash } from "@/lib/format";

type Transparency = {
  supply: { cusdcSupply: string };
  reserve: { usdBalance: string; coveragePercent: string; isFullyBacked: boolean; bankingPartner: string };
  attestation: {
    latest: { date: string; attestor: string } | null;
    history: Array<{ id: string; date: string; coveragePercent: string; anchorTxHash: string; isFullyBacked: boolean }>;
  };
  anchorProof: { anchoredEntries: number; latestAnchorTxHash: string; chainIntegrity: { valid: boolean; entriesChecked: number; brokenAtSeq: number | null } };
  contracts: Record<string, string | boolean | number>;
  corridor: { settledCount: number; averageCostPercent: string; medianSettlementSeconds: number; benchmarkSubSaharanAfrica: string };
};

export default function TransparencyPage() {
  const [d, setD] = useState<Transparency | null>(null);

  useEffect(() => {
    void (async () => { try { setD(await api<Transparency>("/transparency")); } catch { setD(null); } })();
  }, []);

  return (
    <div className="min-h-screen bg-white">
      <header className="mx-auto flex max-w-3xl items-center justify-between px-6 py-6">
        <Link href="/" className="flex items-center gap-2">
          <CowrieMark className="h-6 w-6 text-violet-600" />
          <span className="text-[15px] font-semibold tracking-tight text-heading">Cowrie</span>
        </Link>
        <span className="text-[13px] text-subtle">Transparency</span>
      </header>

      <main id="main" className="mx-auto max-w-3xl px-6 pb-20">
        <h1 className="mt-6 text-[28px] font-bold tracking-tight text-heading">cUSDC reserves</h1>
        <p className="mt-2 max-w-lg text-[14px] leading-relaxed text-muted">
          Every cUSDC is backed one-to-one by dollars held with a regulated banking partner.
        </p>

        {/* headline figures */}
        <dl className="mt-10 flex flex-wrap gap-x-14 gap-y-8">
          <Figure label="In circulation" value={d ? groupDigits(d.supply.cusdcSupply).whole : null} unit="cUSDC" />
          <Figure label="USD held" value={d ? `$${groupDigits(d.reserve.usdBalance).whole}` : null} />
          <Figure label="Coverage" value={d ? `${d.reserve.coveragePercent}%` : null} ok={d?.reserve.isFullyBacked} />
        </dl>

        <Section title="Corridor">
          <dl className="flex flex-wrap gap-x-14 gap-y-8">
            <Figure label="Transfers settled" value={d ? String(d.corridor.settledCount) : null} small />
            <Figure label="Average cost" value={d ? `${d.corridor.averageCostPercent}%` : null} ok small />
            <Figure label="Median settlement" value={d ? `${d.corridor.medianSettlementSeconds}s` : null} ok small />
            <Figure label="Regional average" value={d ? `${d.corridor.benchmarkSubSaharanAfrica}%` : null} small />
          </dl>
        </Section>

        <Section title="Audit chain">
          <p className="text-[14px] text-muted">
            {d ? (
              d.anchorProof.chainIntegrity.valid ? (
                <>
                  <span className="font-semibold text-success">Verified</span> ·{" "}
                  {d.anchorProof.chainIntegrity.entriesChecked} entries · {d.anchorProof.anchoredEntries} anchored on-chain
                </>
              ) : (
                <span className="font-semibold text-danger">Broken at entry #{d.anchorProof.chainIntegrity.brokenAtSeq}</span>
              )
            ) : "—"}
          </p>
          {d?.anchorProof.latestAnchorTxHash ? (
            <p className="mt-2 flex items-center gap-1.5 text-[13px]">
              <span className="text-subtle">Latest anchor</span>
              <code className="font-mono text-ink">{truncateHash(d.anchorProof.latestAnchorTxHash, 10, 6)}</code>
              <CopyButton value={d.anchorProof.latestAnchorTxHash} label="anchor hash" />
            </p>
          ) : null}
        </Section>

        <Section title="Attestations" meta={d?.attestation.latest ? `${d.attestation.latest.attestor} · ${relativeTime(d.attestation.latest.date)}` : undefined}>
          <ul className="divide-y divide-line">
            {(d?.attestation.history ?? []).slice(0, 6).map((a) => (
              <li key={a.id} className="flex items-center gap-4 py-2.5 text-[13px]">
                <span className="w-24 shrink-0 text-muted">
                  {new Date(a.date).toLocaleDateString(undefined, { month: "short", year: "numeric" })}
                </span>
                <span className={cx("w-20 font-semibold tabular-nums", a.isFullyBacked ? "text-success" : "text-danger")}>
                  {a.coveragePercent}%
                </span>
                <code className="truncate font-mono text-[11px] text-subtle">{truncateHash(a.anchorTxHash, 8, 4)}</code>
              </li>
            ))}
            {!d ? <li className="py-3"><Skeleton className="h-5 w-full" /></li> : null}
          </ul>
        </Section>

        <Section title="Contracts">
          <ul className="divide-y divide-line">
            {["cUSDC", "cNGN", "CowrieBridge"].map((name) => (
              <li key={name} className="flex items-center gap-3 py-2.5 text-[13px]">
                <span className="w-28 shrink-0 font-medium text-heading">{name}</span>
                <code className="min-w-0 flex-1 truncate font-mono text-[12px] text-muted">
                  {String(d?.contracts[name] ?? "—")}
                </code>
                {d?.contracts[name] ? <CopyButton value={String(d.contracts[name])} label={`${name} address`} /> : null}
              </li>
            ))}
          </ul>
        </Section>

      </main>
    </div>
  );
}

function Section({ title, meta, children }: { title: string; meta?: string; children: React.ReactNode }) {
  return (
    <section className="mt-12 border-t border-line pt-8">
      <div className="mb-4 flex items-baseline justify-between gap-4">
        <h2 className="text-[15px] font-semibold text-heading">{title}</h2>
        {meta ? <p className="text-[12px] text-subtle">{meta}</p> : null}
      </div>
      {children}
    </section>
  );
}

function Figure({ label, value, unit, ok, small }: { label: string; value: string | null; unit?: string; ok?: boolean; small?: boolean }) {
  return (
    <div>
      <dt className="text-[12px] text-subtle">{label}</dt>
      {value === null ? <Skeleton className="mt-1.5 h-7 w-20" /> : (
        <dd className={cx("mt-1 font-bold tabular-nums tracking-tight", small ? "text-[20px]" : "text-[28px]", ok ? "text-success" : "text-heading")}>
          {value}{unit ? <span className="ml-1.5 text-[12px] font-medium text-subtle">{unit}</span> : null}
        </dd>
      )}
    </div>
  );
}
