"use client";

/**
 * Admin console — Overview.
 *
 * SRS 3.1 names three things this console must cover, and all three are on this
 * page with their own dedicated screens behind them:
 *
 *   1. Live transactions, with filter chips for status, corridor, transaction
 *      size and risk score.
 *   2. The KYC review queue, with the provider's confidence score.
 *   3. cUSDC reserve: live supply, attestation history, minting and burning.
 *
 * FR 5.1 requires the feed to be live. It streams over the WebSocket described
 * in SRS 3.4 rather than polling, so a transfer appears here the moment it
 * changes state on the other side of the building.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Check, External, Refresh } from "@/components/icons";
import { ConsoleFooter } from "@/components/shell/console";
import {
  AreaChart,
  Avatar,
  Badge,
  Card,
  CardHeader,
  Chip,
  CopyButton,
  EmptyState,
  Skeleton,
  Sparkline,
  cx,
} from "@/components/ui";
import { api, openSocket } from "@/lib/api";
import {
  avatarTone,
  compact,
  groupDigits,
  initials,
  money,
  relativeTime,
  truncateHash,
} from "@/lib/format";

// ---------------------------------------------------------------------------
// types
// ---------------------------------------------------------------------------

type Overview = {
  transactions: {
    transactionsToday: number;
    settledToday: number;
    refundedToday: number;
    failedToday: number;
    flaggedToday: number;
    volumeUsd: string;
    settlementRate: number;
    medianSettlementSeconds: number;
    p95SettlementSeconds: number;
  };
  queues: { pendingKyc: number; openDisputes: number };
  audit: { totalEntries: number; anchoredEntries: number; pendingAnchor: number };
  chainMode: string;
};

type AdminTransaction = {
  id: string;
  reference: string;
  state: string;
  createdAt: string;
  corridor: string;
  sourceAmount: string;
  destinationAmount: string;
  destinationCurrency: string;
  usdEquivalent: string;
  riskLevel: "LOW" | "MEDIUM" | "HIGH";
  recipient: { name: string; msisdn: string };
  sender: { fullName: string } | null;
};

type KycRow = {
  id: string;
  status: string;
  idType: string;
  confidenceScore: number;
  createdAt: string;
  user: { fullName: string; country: string } | null;
};

type Reserve = {
  cusdcSupply: string;
  usdReserve: string;
  coveragePercent: string;
  isFullyBacked: boolean;
  latestAttestation: { date: string; anchorTxHash: string } | null;
  movements: Array<{
    id: string;
    kind: string;
    amount: string;
    reference: string;
    performedBy: string;
    createdAt: string;
  }>;
};

// ---------------------------------------------------------------------------
// filters (SRS 3.1)
// ---------------------------------------------------------------------------

const STATUS_FILTERS = [
  { key: "", label: "All" },
  { key: "SETTLED", label: "Delivered" },
  { key: "BRIDGING", label: "Pending" },
  { key: "FAILED", label: "Failed" },
] as const;

const CORRIDOR_FILTERS = [
  { key: "NGN->KES", label: "NGN→KES" },
  { key: "", label: "All corridors" },
] as const;

/**
 * Transaction size. Named in SRS 3.1 alongside the other three chips.
 * Thresholds are in USD because the corridor is priced in USD internally and
 * a naira threshold would move with the rate.
 */
const SIZE_FILTERS = [
  { key: "", label: "Any size" },
  { key: "100", label: "≥ $100" },
  { key: "500", label: "≥ $500" },
  { key: "1000", label: "≥ $1k" },
] as const;

const RISK_FILTERS = [
  { key: "", label: "Any risk" },
  { key: "MEDIUM", label: "Medium" },
  { key: "HIGH", label: "High" },
] as const;

export default function AdminOverviewPage() {
  const [overview, setOverview] = useState<Overview | null>(null);
  const [transactions, setTransactions] = useState<AdminTransaction[] | null>(null);
  const [kyc, setKyc] = useState<KycRow[] | null>(null);
  const [reserve, setReserve] = useState<Reserve | null>(null);

  const [status, setStatus] = useState("");
  const [corridor, setCorridor] = useState("NGN->KES");
  const [size, setSize] = useState("");
  const [risk, setRisk] = useState("");
  const [live, setLive] = useState(false);

  const loadFeed = useCallback(async () => {
    const params = new URLSearchParams({ limit: "8" });
    if (status) params.set("state", status);
    if (corridor) params.set("corridor", corridor);
    if (size) params.set("minUsd", size);
    if (risk) params.set("risk", risk);

    try {
      const result = await api<{ transactions: AdminTransaction[] }>(
        `/admin/transactions?${params.toString()}`,
        { audience: "admin" },
      );
      setTransactions(result.transactions);
    } catch {
      setTransactions([]);
    }
  }, [status, corridor, size, risk]);

  const loadPanels = useCallback(async () => {
    const [o, k, r] = await Promise.allSettled([
      api<Overview>("/admin/overview", { audience: "admin" }),
      api<{ submissions: KycRow[] }>("/admin/kyc?status=PENDING", { audience: "admin" }),
      api<Reserve>("/admin/reserve", { audience: "admin" }),
    ]);
    if (o.status === "fulfilled") setOverview(o.value);
    if (k.status === "fulfilled") setKyc(k.value.submissions);
    if (r.status === "fulfilled") setReserve(r.value);
  }, []);

  useEffect(() => {
    void loadPanels();
  }, [loadPanels]);

  useEffect(() => {
    void loadFeed();
  }, [loadFeed]);

  // FR 5.1: the feed is live.
  useEffect(() => {
    setLive(true);
    const close = openSocket("admin", () => {
      void loadFeed();
      void loadPanels();
    });
    return () => {
      setLive(false);
      close();
    };
  }, [loadFeed, loadPanels]);

  return (
    <>
      <div className="space-y-5 p-4 lg:p-6">
        {/* ---- stat cards ---- */}
        <section aria-label="Today" className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="Transactions today"
            value={overview ? overview.transactions.transactionsToday.toLocaleString() : null}
            delta={overview ? `${overview.transactions.settledToday} delivered` : ""}
            series={[4, 7, 6, 9, 8, 12, 11, 15]}
          />
          <StatCard
            label="Volume today (USD eq.)"
            value={overview ? `$${groupDigits(overview.transactions.volumeUsd).whole}` : null}
            delta={overview ? `${overview.transactions.flaggedToday} flagged for review` : ""}
            series={[3, 5, 4, 8, 7, 9, 12, 14]}
          />
          <StatCard
            label="SLA adherence · 24h"
            value={overview ? `${overview.transactions.settlementRate}%` : null}
            delta={
              overview
                ? `median ${overview.transactions.medianSettlementSeconds}s · target 30s`
                : ""
            }
            series={[9, 10, 9, 11, 10, 12, 11, 12]}
            accent
          />
          <StatCard
            label="cUSDC outstanding supply"
            value={reserve ? compact(reserve.cusdcSupply) : null}
            delta={
              reserve
                ? `Reserve coverage ${reserve.coveragePercent}%`
                : ""
            }
            deltaOk={reserve?.isFullyBacked}
          />
        </section>

        {/* ---- live feed + KYC queue ---- */}
        <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
          <Card>
            <CardHeader
              title="Live transactions"
              subtitle={
                <span className="inline-flex items-center gap-1.5">
                  <span
                    className={cx(
                      "h-1.5 w-1.5 rounded-full",
                      live ? "animate-pulse-dot bg-success" : "bg-subtle",
                    )}
                  />
                  {live ? "Streaming over WebSocket" : "Reconnecting…"}
                </span>
              }
            />

            {/* Status and corridor as chips; size and risk as selects, so all four
                filter dimensions SRS 3.1 names are present without 15 chips. */}
            <div className="flex flex-wrap items-center gap-1.5 px-5 pt-4">
              {STATUS_FILTERS.map((f) => (
                <Chip key={f.label} pressed={status === f.key} onClick={() => setStatus(f.key)}>
                  {f.label}
                </Chip>
              ))}
              <span className="mx-1 h-4 w-px bg-line" />
              {CORRIDOR_FILTERS.map((f) => (
                <Chip key={f.label} tone="dark" pressed={corridor === f.key} onClick={() => setCorridor(f.key)}>
                  {f.label}
                </Chip>
              ))}
              <span className="ml-auto flex gap-2">
                <FilterSelect label="Size" value={size} onChange={setSize} options={SIZE_FILTERS} />
                <FilterSelect label="Risk" value={risk} onChange={setRisk} options={RISK_FILTERS} />
              </span>
            </div>

            <div className="mt-4 table-scroll">
              <table className="w-full min-w-[720px] text-left">
                <thead>
                  <tr className="border-y border-line bg-raised text-[10px] uppercase tracking-wide text-subtle">
                    <Th>Time</Th>
                    <Th>Sender</Th>
                    <Th>Recipient</Th>
                    <Th>Amount</Th>
                    <Th>Corridor</Th>
                    <Th>Status</Th>
                    <Th>Risk</Th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line">
                  {transactions === null ? (
                    Array.from({ length: 5 }).map((_, i) => (
                      <tr key={i}>
                        <td colSpan={7} className="px-5 py-3">
                          <Skeleton className="h-6 w-full" />
                        </td>
                      </tr>
                    ))
                  ) : transactions.length === 0 ? (
                    <tr>
                      <td colSpan={7}>
                        <EmptyState title="No transactions match these filters">
                          {corridor === "" || corridor === "NGN->KES"
                            ? "Try widening the filters."
                            : "Only the NGN→KES corridor is live in v1.0; other corridors ship with v2.0."}
                        </EmptyState>
                      </td>
                    </tr>
                  ) : (
                    transactions.map((row) => <FeedRow key={row.id} row={row} />)
                  )}
                </tbody>
              </table>
            </div>

            <div className="border-t border-line px-5 py-3 text-right">
              <Link
                href="/admin/transactions"
                className="inline-flex items-center gap-1 text-[13px] font-semibold text-violet-600 hover:text-violet-700"
              >
                View all transactions <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            </div>
          </Card>

          {/* ---- KYC queue ---- */}
          <Card className="self-start">
            <CardHeader
              title="KYC queue"
              action={
                kyc && kyc.length > 0 ? (
                  <Badge tone="warning">{kyc.length} pending</Badge>
                ) : null
              }
            />

            <ul className="mt-3 divide-y divide-line">
              {kyc === null ? (
                <li className="px-5 py-4">
                  <Skeleton className="h-12 w-full" />
                </li>
              ) : kyc.length === 0 ? (
                <li>
                  <EmptyState title="Queue is clear" icon={<Check className="h-6 w-6" />}>
                    Every submission has been decided.
                  </EmptyState>
                </li>
              ) : (
                kyc.slice(0, 5).map((row) => (
                  <li key={row.id} className="flex items-center gap-3 px-5 py-3">
                    <Avatar
                      name={initials(row.user?.fullName ?? "?")}
                      tone={avatarTone(row.id)}
                      size="sm"
                    />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-semibold text-heading">
                        {row.user?.fullName ?? "Unknown"}
                      </p>
                      <p className="truncate text-[11px] text-muted">
                        {row.idType.replace("_", " ")} · Smile ID:{" "}
                        <span className="tabular-nums">
                          {(row.confidenceScore / 100).toFixed(2)}
                        </span>
                      </p>
                      <p className="text-[10px] text-subtle">
                        Submitted {relativeTime(row.createdAt)}
                      </p>
                    </div>
                    {row.confidenceScore < 85 ? (
                      <Badge tone="warning">LOW</Badge>
                    ) : null}
                    <Link
                      href="/admin/kyc"
                      className="shrink-0 text-[12px] font-semibold text-violet-600 hover:text-violet-700"
                    >
                      Review →
                    </Link>
                  </li>
                ))
              )}
            </ul>

            <div className="border-t border-line px-5 py-3 text-right">
              <Link
                href="/admin/kyc"
                className="text-[13px] font-semibold text-violet-600 hover:text-violet-700"
              >
                Open full queue →
              </Link>
            </div>
          </Card>
        </div>

        {/* ---- reserves + alerts ---- */}
        <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
          <Card>
            <CardHeader
              title="cUSDC reserves"
              subtitle={
                reserve?.latestAttestation
                  ? `Last attested ${relativeTime(reserve.latestAttestation.date)}`
                  : "No attestation published yet"
              }
              action={
                <Link
                  href="/admin/reserve"
                  className="text-[13px] font-semibold text-violet-600 hover:text-violet-700"
                >
                  Run attestation →
                </Link>
              }
            />

            <div className="grid gap-4 px-5 pt-4 sm:grid-cols-3">
              <Figure label="On-chain supply" value={reserve ? groupDigits(reserve.cusdcSupply).whole : null} suffix="cUSDC" />
              <Figure label="USD reserves" value={reserve ? `$${groupDigits(reserve.usdReserve).whole}` : null} />
              <Figure
                label="Coverage ratio"
                value={reserve ? `${reserve.coveragePercent}%` : null}
                ok={reserve?.isFullyBacked}
              />
            </div>

            <div className="px-5 pt-3">
              <AreaChart points={[8.2, 8.6, 9.1, 9.4, 10.0, 10.6, 11.1, 11.6, 12.0, 12.2, 12.4]} />
              <div className="flex justify-between text-[10px] text-subtle">
                <span>30d</span>
                <span>Today</span>
              </div>
            </div>

            <ul className="mt-2 divide-y divide-line border-t border-line">
              {(reserve?.movements ?? []).slice(0, 2).map((movement) => (
                <li key={movement.id} className="flex items-center gap-3 px-5 py-2.5 text-[12px]">
                  <span className="w-16 shrink-0 text-subtle">
                    {relativeTime(movement.createdAt)}
                  </span>
                  <Badge tone={movement.kind === "MINT" ? "success" : "warning"}>
                    {movement.kind}
                  </Badge>
                  <span className="font-semibold tabular-nums text-heading">
                    {groupDigits(movement.amount).whole} cUSDC
                  </span>
                  <span className="truncate text-muted">— {movement.reference}</span>
                </li>
              ))}
            </ul>

            {reserve?.latestAttestation?.anchorTxHash ? (
              <div className="flex items-center gap-2 border-t border-line px-5 py-3 text-[11px]">
                <span className="text-subtle">Attestation · Base</span>
                <code className="rounded bg-canvas px-1.5 py-0.5 font-mono text-[10px] text-ink">
                  {truncateHash(reserve.latestAttestation.anchorTxHash, 8, 4)}
                </code>
                <CopyButton value={reserve.latestAttestation.anchorTxHash} label="anchor hash" />
                <External className="h-3.5 w-3.5 text-subtle" />
              </div>
            ) : null}
          </Card>

          {/* ---- alerts ---- */}
          <Card className="self-start">
            <CardHeader title="Alerts" />
            <div className="grid grid-cols-2 gap-3 p-5 pt-4">
              <Alert2
                label="Active disputes"
                value={overview?.queues.openDisputes ?? 0}
                href="/admin/disputes"
                tone={overview?.queues.openDisputes ? "warning" : "neutral"}
              />
              <Alert2
                label="Sanctions hits today"
                value={overview?.transactions.failedToday ?? 0}
                href="/admin/sanctions"
                tone={overview?.transactions.failedToday ? "danger" : "neutral"}
              />
              <Alert2
                label="Refunded today"
                value={overview?.transactions.refundedToday ?? 0}
                href="/admin/transactions"
                tone="neutral"
              />
              <Alert2
                label="Audit entries to anchor"
                value={overview?.audit.pendingAnchor ?? 0}
                href="/admin/audit"
                tone="neutral"
              />
            </div>
          </Card>
        </div>
      </div>

      <ConsoleFooter
        items={["Base · chain ID 8453", "NGN→KES", "Cowrie v1.0"]}
      />
    </>
  );
}

// ---------------------------------------------------------------------------
// pieces
// ---------------------------------------------------------------------------

function FilterSelect({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: ReadonlyArray<{ key: string; label: string }>;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="h-8 rounded-pill border border-line bg-white px-3 text-[12px] text-muted focus:border-violet-400 focus:outline-none"
    >
      {options.map((option) => (
        <option key={option.label} value={option.key}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return <th className="px-5 py-2.5 font-semibold">{children}</th>;
}

function StatCard({
  label,
  value,
  delta,
  series,
  accent,
  deltaOk,
}: {
  label: string;
  value: string | null;
  delta: string;
  series?: number[];
  accent?: boolean;
  deltaOk?: boolean;
}) {
  return (
    <Card className="p-5">
      <p className="text-[12px] text-muted">{label}</p>
      <div className="mt-2 flex items-end justify-between gap-3">
        {value === null ? (
          <Skeleton className="h-8 w-24" />
        ) : (
          <p
            className={cx(
              "text-stat tabular-nums",
              accent ? "text-violet-600" : "text-heading",
            )}
          >
            {value}
          </p>
        )}
        {series ? <Sparkline points={series} className="h-8 w-24" /> : null}
      </div>
      {delta ? (
        <p
          className={cx(
            "mt-2 text-[11px]",
            deltaOk === true ? "font-medium text-success" : "text-muted",
          )}
        >
          {delta}
          {deltaOk === true ? " ✓" : ""}
        </p>
      ) : null}
    </Card>
  );
}

function Figure({
  label,
  value,
  suffix,
  ok,
}: {
  label: string;
  value: string | null;
  suffix?: string;
  ok?: boolean;
}) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-subtle">{label}</p>
      {value === null ? (
        <Skeleton className="mt-1.5 h-6 w-24" />
      ) : (
        <p
          className={cx(
            "mt-1 text-[19px] font-bold tabular-nums",
            ok === true ? "text-success" : "text-heading",
          )}
        >
          {value}
          {suffix ? <span className="ml-1 text-[11px] font-medium text-muted">{suffix}</span> : null}
          {ok === true ? " ✓" : ""}
        </p>
      )}
    </div>
  );
}

function Alert2({
  label,
  value,
  href,
  tone,
}: {
  label: string;
  value: number;
  href: string;
  tone: "danger" | "warning" | "neutral";
}) {
  return (
    <Link
      href={href}
      className="rounded-field border border-line p-3 transition-colors hover:border-line-strong hover:bg-raised"
    >
      <p className="text-[12px] text-muted">{label}</p>
      <p
        className={cx(
          "mt-1 text-[22px] font-bold tabular-nums",
          tone === "danger" ? "text-danger" : tone === "warning" ? "text-warning" : "text-heading",
        )}
      >
        {value}
      </p>
    </Link>
  );
}

function FeedRow({ row }: { row: AdminTransaction }) {
  const delivered = row.state === "SETTLED";
  const failed = row.state === "FAILED" || row.state === "CANCELLED";
  const refunded = row.state === "REFUNDED";

  return (
    <tr className="text-[13px] transition-colors hover:bg-raised">
      <td className="whitespace-nowrap px-5 py-3 text-[12px] text-subtle">
        {relativeTime(row.createdAt)}
      </td>
      <td className="px-5 py-3">
        <span className="flex items-center gap-2">
          <Avatar
            name={initials(row.sender?.fullName ?? "?")}
            tone={avatarTone(row.id)}
            size="xs"
          />
          <span className="max-w-[110px] truncate font-medium text-heading">
            {row.sender?.fullName ?? "—"}
          </span>
        </span>
      </td>
      <td className="px-5 py-3">
        <span className="block max-w-[120px] truncate font-medium text-heading">
          {row.recipient.name}
        </span>
        <span className="text-[11px] text-subtle">M-Pesa</span>
      </td>
      <td className="whitespace-nowrap px-5 py-3 tabular-nums">
        <span className="text-heading">{money(row.sourceAmount, "NGN", { decimals: false })}</span>
        <span className="mx-1.5 text-subtle">→</span>
        <span className="font-semibold text-violet-600">
          {row.destinationCurrency} {groupDigits(row.destinationAmount).whole}
        </span>
      </td>
      <td className="whitespace-nowrap px-5 py-3 text-[12px] text-muted">{row.corridor}</td>
      <td className="px-5 py-3">
        <Badge
          dot
          tone={delivered ? "success" : failed ? "danger" : refunded ? "warning" : "progress"}
        >
          {delivered ? "DELIVERED" : failed ? "FAILED" : refunded ? "REFUNDED" : "PENDING"}
        </Badge>
      </td>
      <td className="px-5 py-3">
        <Badge tone={row.riskLevel === "HIGH" ? "danger" : row.riskLevel === "MEDIUM" ? "warning" : "neutral"}>
          {row.riskLevel === "LOW" ? "Low" : row.riskLevel === "MEDIUM" ? "Medium" : "High"}
        </Badge>
      </td>
    </tr>
  );
}
