"use client";
/** CowriePay — Receive / Top up (the other two action keys from SRS 3.1). */
import Link from "next/link";
import { ChevronLeft, Wallet } from "@/components/icons";
import { Card, CopyButton, Notice, Skeleton } from "@/components/ui";
import { TabBar } from "@/components/pay/tab-bar";
import { useRequireSession } from "@/components/pay/session";
import { money, prettyMsisdn } from "@/lib/format";

export default function ReceivePage() {
  const { user, loading } = useRequireSession();
  if (loading || !user) return <Skeleton className="m-5 h-64" />;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin pb-4">
        <header className="flex items-center gap-2 px-5 pb-2 pt-3">
          <Link href="/pay" className="flex h-9 w-9 items-center justify-center rounded-full text-muted hover:bg-canvas" aria-label="Back to home"><ChevronLeft /></Link>
          <h1 className="text-[15px] font-semibold text-heading">Receive & top up</h1>
        </header>

        <div className="space-y-4 px-5 pt-2">
          <Card className="p-5 text-center">
            <p className="eyebrow">Your Cowrie number</p>
            <p className="mt-2 text-[22px] font-bold tabular-nums text-heading">{prettyMsisdn(user.phone)}</p>
            <div className="mt-2 flex justify-center"><CopyButton value={user.phone} label="phone number" /></div>
            <p className="mt-2 text-[13px] text-muted">Anyone on Cowrie can send to this number.</p>
          </Card>

          <Card className="p-5">
            <p className="flex items-center gap-2 text-[15px] font-semibold text-heading"><Wallet className="h-4 w-4 text-violet-600" />Top up your naira wallet</p>
            <p className="mt-1.5 text-[13px] text-muted">Funds are pulled from the bank account linked through Mono.</p>
            <dl className="mt-4 space-y-2 text-[13px]">
              <div className="flex justify-between"><dt className="text-muted">Linked bank</dt><dd className="font-medium text-ink">{user.bankName || "Not linked"}</dd></div>
              <div className="flex justify-between"><dt className="text-muted">Account</dt><dd className="font-medium tabular-nums text-ink">{user.bankAccountMasked || "—"}</dd></div>
              <div className="flex justify-between"><dt className="text-muted">Current balance</dt><dd className="font-bold tabular-nums text-ink">{money(user.ngnBalance, "NGN")}</dd></div>
            </dl>
          </Card>


        </div>
      </div>
      <TabBar />
    </div>
  );
}
