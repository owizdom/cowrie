"use client";

/**
 * CowriePay — transfer status.
 *
 * SRS 3.4 puts transaction status on a WebSocket rather than polling, so this
 * screen subscribes and is pushed each state change and each new confirmation
 * count. It also polls slowly as a backstop: if the socket cannot connect at
 * all — a proxy that strips upgrades, say — the screen still advances rather
 * than sitting frozen while the money moves.
 *
 * The five steps shown are the happy path of the state machine diagram. When a
 * transfer leaves that path (refund or failure) the tracker is replaced with
 * the outcome, because showing progress through steps that will never complete
 * would be a lie about where the money is.
 *
 * FR 2.4: once a transfer has been pending past the threshold, the "Cancel and
 * refund" button appears here.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Bolt, Check, ChevronLeft, Copy, External, Refresh, ShieldCheck } from "@/components/icons";
import { Avatar, Button, Card, CopyButton, LiveRegion, Notice, Skeleton, cx } from "@/components/ui";
import { TabBar } from "@/components/pay/tab-bar";
import { useRequireSession } from "@/components/pay/session";
import { api, openSocket, type Transfer } from "@/lib/api";
import {
  avatarTone,
  fullTimestamp,
  groupDigits,
  initials,
  money,
  prettyMsisdn,
  SETTLEMENT_STEPS,
  STATE_PRESENTATION,
  stepIndex,
  TONE_CLASSES,
  TONE_DOT,
} from "@/lib/format";

const TERMINAL = new Set(["SETTLED", "REFUNDED", "FAILED", "CANCELLED"]);

export default function StatusPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { user, loading } = useRequireSession();

  const [transfer, setTransfer] = useState<Transfer | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [cancelling, setCancelling] = useState(false);
  const [error, setError] = useState("");
  const startedAt = useRef<number>(Date.now());

  const load = useCallback(async () => {
    try {
      const result = await api<Transfer>(`/transfers/${id}`, { audience: "cowriepay" });
      setTransfer(result);
      return result;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load that transfer.");
      return null;
    }
  }, [id]);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  // Push updates (SRS 3.4).
  useEffect(() => {
    if (!user) return;
    return openSocket("transfers", (event) => {
      if (event.data?.transactionId === id) void load();
    });
  }, [user, id, load]);

  // Backstop poll, only while the transfer is still moving.
  useEffect(() => {
    if (!transfer || TERMINAL.has(transfer.state)) return;
    const timer = setInterval(() => void load(), 2500);
    return () => clearInterval(timer);
  }, [transfer, load]);

  // Elapsed counter, so the NFR 1 claim is visible rather than asserted.
  useEffect(() => {
    if (!transfer) return;
    if (TERMINAL.has(transfer.state)) return;
    startedAt.current = new Date(transfer.createdAt).getTime();
    const timer = setInterval(
      () => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000)),
      1000,
    );
    return () => clearInterval(timer);
  }, [transfer]);

  const cancel = useCallback(async () => {
    setCancelling(true);
    setError("");
    try {
      await api(`/transfers/${id}/cancel`, { method: "POST", audience: "cowriepay" });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not cancel.");
    } finally {
      setCancelling(false);
    }
  }, [id, load]);

  if (loading || !transfer) {
    return (
      <div className="space-y-4 px-5 pt-6">
        <Skeleton className="h-8 w-32" />
        <Skeleton className="h-40 w-full rounded-card" />
        <Skeleton className="h-56 w-full rounded-card" />
      </div>
    );
  }

  const presentation = STATE_PRESENTATION[transfer.state];
  const active = stepIndex(transfer.state);
  const offPath = active === -1;
  const settled = transfer.state === "SETTLED";
  const refunded = transfer.state === "REFUNDED";
  const failed = transfer.state === "FAILED" || transfer.state === "CANCELLED";
  const onchain = transfer.onchain;

  const settledSeconds =
    transfer.settledAt && transfer.createdAt
      ? Math.round(
          (new Date(transfer.settledAt).getTime() - new Date(transfer.createdAt).getTime()) / 1000,
        )
      : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin pb-4">
        <header className="flex items-center gap-2 px-5 pb-2 pt-3">
          <Link
            href="/pay"
            className="flex h-9 w-9 items-center justify-center rounded-full text-muted transition-colors hover:bg-canvas"
            aria-label="Back to home"
          >
            <ChevronLeft />
          </Link>
          <h1 className="text-[15px] font-semibold text-heading">Transfer</h1>
          <span className="ml-auto font-mono text-[11px] text-subtle">{transfer.reference}</span>
        </header>

        <LiveRegion message={`${presentation.label}. ${presentation.detail}.`} />

        {/* ---- outcome ---- */}
        <section className="px-5 pt-2">
          <div
            className={cx(
              "rounded-panel border p-5 text-center",
              settled
                ? "border-success-ring bg-success-bg"
                : refunded
                  ? "border-warning-ring bg-warning-bg"
                  : failed
                    ? "border-danger-ring bg-danger-bg"
                    : "border-violet-100 bg-violet-50",
            )}
          >
            <span
              className={cx(
                "mx-auto flex h-14 w-14 items-center justify-center rounded-full",
                settled
                  ? "bg-success text-white"
                  : refunded || failed
                    ? "bg-white text-warning"
                    : "bg-white text-violet-600",
              )}
            >
              {settled ? (
                <Check className="h-7 w-7" />
              ) : refunded || failed ? (
                <Refresh className="h-6 w-6" />
              ) : (
                <span className="flex h-6 w-6 items-center justify-center">
                  <span className="h-3 w-3 animate-pulse-dot rounded-full bg-violet-600" />
                </span>
              )}
            </span>

            <p className="mt-3 text-[17px] font-bold text-heading">{presentation.label}</p>
            <p className="mt-1 text-[13px] text-muted">
              {transfer.failureReason || presentation.detail}
            </p>

            {settled && settledSeconds !== null ? (
              <p className="mt-2 text-[12px] font-semibold text-success">
                Delivered in {settledSeconds} seconds
              </p>
            ) : !TERMINAL.has(transfer.state) ? (
              <p className="mt-2 text-[12px] tabular-nums text-muted">{elapsed}s elapsed</p>
            ) : null}
          </div>
        </section>

        {/* ---- amounts ---- */}
        <section className="px-5 pt-4">
          <Card className="px-4 py-4">
            <div className="flex items-center gap-3">
              <Avatar
                name={initials(transfer.recipient.name)}
                tone={avatarTone(transfer.recipient.msisdn)}
                size="md"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold text-heading">
                  {transfer.recipient.name}
                </p>
                <p className="truncate text-[12px] text-muted">
                  {prettyMsisdn(transfer.recipient.msisdn)}
                </p>
              </div>
            </div>

            <div className="divider my-3.5" />

            <div className="flex items-center justify-between">
              <div>
                <p className="text-[11px] text-subtle">You sent</p>
                <p className="text-[17px] font-bold tabular-nums text-heading">
                  {money(transfer.source.amount, "NGN", { decimals: false })}
                </p>
              </div>
              <div className="text-right">
                <p className="text-[11px] text-subtle">They receive</p>
                <p className="text-[17px] font-bold tabular-nums text-violet-600">
                  KES {groupDigits(transfer.destination.amount).whole}.
                  {groupDigits(transfer.destination.amount).fraction}
                </p>
              </div>
            </div>

            <div className="divider my-3.5" />

            {/* NFR 6: the four components stay itemised on the receipt too. */}
            <dl className="space-y-2 text-[12px]">
              <Line label="FX spread" value={money(transfer.fees.fxSpread, "NGN")} />
              <Line label="Network gas" value={money(transfer.fees.networkGas, "NGN")} />
              <Line label="LP spread" value={money(transfer.fees.liquiditySpread, "NGN")} />
              <Line label="Cowrie service fee" value={money(transfer.fees.cowrieFee, "NGN")} />
              <div className="flex items-center justify-between border-t border-line pt-2">
                <dt className="font-semibold text-heading">Total fee</dt>
                <dd className="font-bold tabular-nums text-heading">
                  {money(transfer.fees.total, "NGN")} · {transfer.costPercent}%
                </dd>
              </div>
            </dl>
          </Card>
        </section>

        {/* ---- progress ---- */}
        {!offPath ? (
          <section className="px-5 pt-4">
            <Card className="px-4 py-4">
              <ol className="space-y-0">
                {SETTLEMENT_STEPS.map((step, index) => {
                  const done = index < active || settled;
                  const current = index === active && !settled;
                  const last = index === SETTLEMENT_STEPS.length - 1;

                  return (
                    <li key={step.state} className="flex gap-3">
                      <div className="flex flex-col items-center">
                        <span
                          className={cx(
                            "flex h-6 w-6 shrink-0 items-center justify-center rounded-full border-2 transition-colors",
                            done
                              ? "border-success bg-success text-white"
                              : current
                                ? "border-violet-600 bg-white"
                                : "border-line bg-white",
                          )}
                        >
                          {done ? (
                            <Check className="h-3.5 w-3.5" />
                          ) : current ? (
                            <span className="h-2 w-2 animate-pulse-dot rounded-full bg-violet-600" />
                          ) : null}
                        </span>
                        {!last ? (
                          <span
                            className={cx(
                              "my-0.5 w-0.5 flex-1",
                              done ? "bg-success" : "bg-line",
                            )}
                            style={{ minHeight: 22 }}
                          />
                        ) : null}
                      </div>

                      <div className={cx("min-w-0 flex-1", last ? "pb-0" : "pb-4")}>
                        <p
                          className={cx(
                            "text-[13px] font-semibold",
                            done || current ? "text-heading" : "text-subtle",
                          )}
                        >
                          {step.label}
                        </p>

                        {/* FR 3.3 made visible: the 12-confirmation wait. */}
                        {step.state === "BRIDGING" && onchain && (current || done) ? (
                          <div className="mt-1.5">
                            <div className="flex items-center justify-between text-[11px] text-muted">
                              <span className="tabular-nums">
                                {onchain.confirmations} of {onchain.requiredConfirmations}{" "}
                                confirmations
                              </span>
                              <span className="tabular-nums">
                                block {onchain.blockNumber.toLocaleString()}
                              </span>
                            </div>
                            <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-line">
                              <div
                                className="h-full rounded-full bg-violet-600 transition-[width] duration-500"
                                style={{
                                  width: `${Math.min(100, (onchain.confirmations / onchain.requiredConfirmations) * 100)}%`,
                                }}
                              />
                            </div>
                          </div>
                        ) : null}

                        {step.state === "SETTLED" && transfer.mpesaReceipt ? (
                          <p className="mt-1 font-mono text-[11px] text-muted">
                            M-Pesa {transfer.mpesaReceipt}
                          </p>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
              </ol>
            </Card>
          </section>
        ) : null}

        {/* ---- FR 2.4 ---- */}
        {transfer.canCancel ? (
          <section className="px-5 pt-4">
            <Notice tone="warning" icon={<Bolt className="h-[18px] w-[18px]" />}>
              <p className="font-semibold text-heading">This transfer is taking longer than usual</p>
              <p className="mt-0.5">
                You can cancel it now and your naira is returned, or leave it — it refunds itself
                automatically after 10 minutes.
              </p>
              <Button
                variant="outline"
                size="sm"
                className="mt-2.5"
                loading={cancelling}
                onClick={cancel}
              >
                Cancel and refund
              </Button>
            </Notice>
          </section>
        ) : null}

        {error ? (
          <div className="px-5 pt-3">
            <Notice tone="danger">{error}</Notice>
          </div>
        ) : null}

        {/* ---- on-chain record ---- */}
        {onchain ? (
          <section className="px-5 pt-4">
            <Card className="px-4 py-4">
              <div className="flex items-center justify-between">
                <h2 className="text-[13px] font-semibold text-heading">Settlement record</h2>
                <span
                  className={cx(
                    "rounded-pill px-2 py-0.5 text-[10px] font-semibold ring-1 ring-inset",
                    onchain.isFinal ? TONE_CLASSES.success : TONE_CLASSES.progress,
                  )}
                >
                  {onchain.isFinal ? "Final" : "Confirming"}
                </span>
              </div>

              <dl className="mt-3 space-y-2 text-[12px]">
                <div className="flex items-center justify-between gap-2">
                  <dt className="text-muted">Transaction</dt>
                  <dd className="flex min-w-0 items-center gap-1">
                    <span className="truncate font-mono text-[11px] text-ink">
                      {onchain.txHash.slice(0, 10)}…{onchain.txHash.slice(-8)}
                    </span>
                    <CopyButton value={onchain.txHash} label="transaction hash" />
                  </dd>
                </div>
                <Line label="Bridged" value={`${onchain.cngnAmount} cNGN → ${onchain.cusdcAmount} cUSDC`} />
                <Line label="Network" value={onchain.chainMode === "anvil" ? "Local chain" : "Base (simulated)"} />
              </dl>

              <p className="mt-3 flex items-start gap-1.5 text-[11px] text-subtle">
                <ShieldCheck className="mt-px h-3.5 w-3.5 shrink-0" />
                This transfer is recorded in a tamper-evident log that is anchored on-chain.
              </p>
            </Card>
          </section>
        ) : null}

        <p className="px-5 pt-4 text-center text-[11px] text-subtle">
          Started {fullTimestamp(transfer.createdAt)}
        </p>
      </div>

      <TabBar />
    </div>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className="truncate font-medium tabular-nums text-ink">{value}</dd>
    </div>
  );
}
