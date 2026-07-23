"use client";

/**
 * CowriePay — Home (screen 02).
 *
 * SRS 3.1: "Home: local currency balance, recent transactions, and action keys
 * (Send, Receive, Top-up)."
 *
 * All three action keys are present. Receive and Top-up are real destinations
 * rather than decoration, because a button that does nothing is worse than an
 * absent one.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Bell, ArrowDown, ArrowUp, Link as LinkIcon, Plus, Scan } from "@/components/icons";
import { Avatar, Skeleton, cx } from "@/components/ui";
import { TabBar } from "@/components/pay/tab-bar";
import { InstallPrompt } from "@/components/pay/install";
import { useRequireSession } from "@/components/pay/session";
import { api, openSocket, type Transfer } from "@/lib/api";
import {
  avatarTone,
  groupDigits,
  initials,
  money,
  relativeTime,
  STATE_PRESENTATION,
  TONE_DOT,
} from "@/lib/format";

export default function HomePage() {
  const { user, loading, refresh } = useRequireSession();
  const [transfers, setTransfers] = useState<Transfer[] | null>(null);

  const load = useCallback(async () => {
    try {
      const result = await api<{ transfers: Transfer[] }>("/transfers?limit=6", {
        audience: "cowriepay",
      });
      setTransfers(result.transfers);
    } catch {
      setTransfers([]);
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  // Keep the list and the balance current while the screen is open: a transfer
  // started on this device settles about thirty seconds later, and the home
  // screen should reflect that without a manual refresh.
  useEffect(() => {
    if (!user) return;
    return openSocket("transfers", (event) => {
      if (
        event.event === "transfer.completed" ||
        event.event === "transfer.refunded" ||
        event.event === "transaction.state_changed"
      ) {
        void load();
        void refresh();
      }
    });
  }, [user, load, refresh]);

  if (loading || !user) {
    return (
      <div className="flex flex-1 flex-col">
        <div className="space-y-4 px-5 pt-4">
          <Skeleton className="h-12 w-full" />
          <Skeleton className="h-40 w-full rounded-panel" />
          <Skeleton className="h-20 w-full" />
        </div>
      </div>
    );
  }

  const { whole, fraction } = groupDigits(user.ngnBalance);
  const firstName = user.fullName.split(" ")[0];
  const surnameInitial = user.fullName.split(" ").slice(-1)[0]?.[0] ?? "";

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin pb-4">
        {/* ---- header ---- */}
        <header className="flex items-center gap-3 px-5 pb-3 pt-3">
          <Avatar name={initials(user.fullName)} tone={avatarTone(user.id)} size="md" />
          <div className="min-w-0 flex-1">
            <p className="text-[11px] text-subtle">{greeting()}</p>
            <p className="truncate text-[15px] font-semibold text-heading">
              {firstName} {surnameInitial}.
            </p>
          </div>

          <Link
            href="/pay/receive"
            className="flex h-9 w-9 items-center justify-center rounded-full border border-line text-muted transition-colors hover:bg-canvas"
            aria-label="Scan to receive"
          >
            <Scan className="h-[18px] w-[18px]" />
          </Link>
          <Link
            href="/pay/history"
            className="relative flex h-9 w-9 items-center justify-center rounded-full border border-line text-muted transition-colors hover:bg-canvas"
            aria-label="Notifications"
          >
            <Bell className="h-[18px] w-[18px]" />
            {/* Only shown when something is genuinely in flight. */}
            {transfers?.some((t) =>
              ["ONRAMP_PENDING", "BRIDGING", "OFFRAMP_PENDING", "REFUNDING"].includes(t.state),
            ) ? (
              <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-violet-600 ring-2 ring-white" />
            ) : null}
          </Link>
        </header>

        <InstallPrompt />

        {/*
          A wallet with nothing in it cannot send, and the Send screen would
          only fail at authorisation. Say so here, with the way out, rather
          than letting someone discover it four steps later.
        */}
        {Number(user.ngnBalance) === 0 ? (
          <div className="mx-5 mb-3 flex items-center gap-3 rounded-card border border-violet-100 bg-violet-50 px-3.5 py-3">
            <Plus className="h-4 w-4 shrink-0 text-violet-600" />
            <p className="min-w-0 flex-1 text-[12px] text-ink">
              {user.bankName ? "Add money to start sending" : "Link a bank account to add money"}
            </p>
            <Link
              href="/pay/receive"
              className="shrink-0 rounded-pill bg-violet-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-violet-700"
            >
              {user.bankName ? "Add" : "Link"}
            </Link>
          </div>
        ) : null}

        {/* ---- balance ---- */}
        <section className="px-5">
          <div className="relative overflow-hidden rounded-panel bg-balance p-5 text-white shadow-balance">
            <span className="absolute inset-0 bg-balance-sheen" aria-hidden="true" />
            <div className="relative">
              <div className="flex items-start justify-between">
                <p className="text-label uppercase text-white/70">Total balance</p>
                <span className="inline-flex items-center gap-1.5 rounded-pill bg-white/15 px-2.5 py-1 text-[10px] font-semibold">
                  <LinkIcon className="h-3 w-3" />
                  on-chain
                </span>
              </div>

              <p className="mt-2.5 flex items-baseline tabular-nums">
                <span className="text-[22px] font-semibold">₦</span>
                <span className="ml-1.5 text-[38px] font-bold leading-none tracking-tight">
                  {whole}
                </span>
                <span className="text-[20px] font-semibold text-white/75">.{fraction}</span>
              </p>

              <div className="mt-5 flex items-center justify-between">
                <Link
                  href="/pay/receive"
                  className="inline-flex items-center gap-1.5 rounded-pill bg-white/15 px-3 py-1.5 text-[12px] font-semibold transition-colors hover:bg-white/25"
                >
                  <Plus className="h-3.5 w-3.5" />
                  Top up
                </Link>
                <p className="text-[11px] text-white/70">Wallet · NGN</p>
              </div>
            </div>
          </div>
        </section>

        {/* ---- action keys (SRS 3.1) ---- */}
        <section className="mt-5 px-5" aria-label="Quick actions">
          <ul className="flex items-start justify-around">
            <ActionKey href="/pay/send" label="Send" primary icon={<ArrowUp className="h-5 w-5" />} />
            <ActionKey href="/pay/receive" label="Receive" icon={<ArrowDown className="h-5 w-5" />} />
            <ActionKey href="/pay/receive" label="Top up" icon={<Plus className="h-5 w-5" />} />
          </ul>
        </section>

        {/* ---- recent activity ---- */}
        <section className="mt-6 px-5">
          <div className="flex items-baseline justify-between">
            <h2 className="text-[15px] font-semibold text-heading">Recent activity</h2>
            <Link href="/pay/history" className="text-[13px] font-semibold text-violet-600">
              See all
            </Link>
          </div>

          <ul className="mt-3 space-y-2">
            {transfers === null ? (
              <>
                <Skeleton className="h-16 w-full rounded-card" />
                <Skeleton className="h-16 w-full rounded-card" />
                <Skeleton className="h-16 w-full rounded-card" />
              </>
            ) : transfers.length === 0 ? (
              <li className="card px-4 py-8 text-center">
                <p className="text-sm font-semibold text-heading">No transfers yet</p>
                <p className="mt-1 text-[13px] text-muted">
                  {Number(user.ngnBalance) > 0
                    ? "A transfer to Kenya takes about thirty seconds."
                    : "Add money first, then send."}
                </p>
                <Link
                  href={Number(user.ngnBalance) > 0 ? "/pay/send" : "/pay/receive"}
                  className="mt-3 inline-block text-[13px] font-semibold text-violet-600"
                >
                  {Number(user.ngnBalance) > 0 ? "Send money" : "Add money"}
                </Link>
              </li>
            ) : (
              transfers.map((transfer) => <ActivityRow key={transfer.id} transfer={transfer} />)
            )}
          </ul>
        </section>
      </div>

      <TabBar />
    </div>
  );
}

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

function ActionKey({
  href,
  label,
  icon,
  primary,
}: {
  href: string;
  label: string;
  icon: React.ReactNode;
  primary?: boolean;
}) {
  return (
    <li className="flex w-20 flex-col items-center">
      <Link
        href={href}
        className={cx(
          "flex h-[52px] w-[52px] items-center justify-center rounded-2xl transition-colors",
          primary
            ? "bg-violet-600 text-white shadow-fab hover:bg-violet-700"
            : "bg-violet-50 text-violet-700 hover:bg-violet-100",
        )}
      >
        {icon}
        <span className="sr-only">{label}</span>
      </Link>
      <span className="mt-2 text-[12px] font-medium text-muted" aria-hidden="true">
        {label}
      </span>
    </li>
  );
}

function ActivityRow({ transfer }: { transfer: Transfer }) {
  const presentation = STATE_PRESENTATION[transfer.state];
  const settled = transfer.state === "SETTLED";
  const returned = transfer.state === "REFUNDED";

  return (
    <li>
      <Link
        href={`/pay/status/${transfer.id}`}
        className="flex items-center gap-3 rounded-card border border-line bg-white px-3.5 py-3 transition-colors hover:border-line-strong"
      >
        <Avatar
          name={initials(transfer.recipient.name)}
          tone={avatarTone(transfer.recipient.msisdn || transfer.id)}
          size="sm"
        />

        <div className="min-w-0 flex-1">
          <p className="flex items-center gap-1.5 text-sm font-semibold text-heading">
            <span className="truncate">{transfer.recipient.name}</span>
            <span
              className={cx("h-1.5 w-1.5 shrink-0 rounded-full", TONE_DOT[presentation.tone])}
              aria-hidden="true"
            />
          </p>
          <p className="truncate text-[12px] text-muted">
            {settled
              ? `Sent · ${money(transfer.destination.amount, "KES", { decimals: false })}`
              : presentation.label}{" "}
            · {relativeTime(transfer.createdAt)}
          </p>
        </div>

        <p
          className={cx(
            "shrink-0 text-sm font-semibold tabular-nums",
            returned ? "text-success" : "text-heading",
          )}
        >
          {returned ? "+" : "−"}
          {money(transfer.source.amount, "NGN", { decimals: false })}
        </p>
      </Link>
    </li>
  );
}
