"use client";
/** CowriePay — profile, support tickets (SRS 2.2 "create a support ticket") and help. */
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Chat, ChevronLeft, IdCard, Book } from "@/components/icons";
import { Avatar, Badge, Button, Card, ErrorText, Skeleton, cx, inputClass } from "@/components/ui";
import { TabBar } from "@/components/pay/tab-bar";
import { useRequireSession } from "@/components/pay/session";
import { api } from "@/lib/api";
import { avatarTone, initials, relativeTime } from "@/lib/format";

type Ticket = { id: string; subject: string; body: string; status: string; createdAt: string; resolution: string };

export default function SupportPage() {
  const { user, loading, signOut } = useRequireSession();
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [reference, setReference] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);

  const load = useCallback(async () => {
    try { setTickets((await api<{ tickets: Ticket[] }>("/support/tickets", { audience: "cowriepay" })).tickets); }
    catch { setTickets([]); }
  }, []);

  useEffect(() => { if (user) void load(); }, [user, load]);

  if (loading || !user) return <Skeleton className="m-5 h-64" />;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin pb-4">
        <header className="flex items-center gap-2 px-5 pb-2 pt-3">
          <Link href="/pay" className="flex h-9 w-9 items-center justify-center rounded-full text-muted hover:bg-canvas" aria-label="Back to home"><ChevronLeft /></Link>
          <h1 className="text-[15px] font-semibold text-heading">Profile & support</h1>
        </header>

        <div className="space-y-4 px-5 pt-2">
          <Card className="flex items-center gap-3 p-4">
            <Avatar name={initials(user.fullName)} tone={avatarTone(user.id)} size="lg" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-semibold text-heading">{user.fullName}</p>
              <p className="truncate text-[12px] text-muted">{user.phone}</p>
              <Badge tone={user.kycLevel === "TIER3" ? "success" : "progress"} className="mt-1">
                {user.kycLevel} · ${user.limitUsd.toLocaleString()} limit
              </Badge>
            </div>
          </Card>

          <div className="grid grid-cols-2 gap-3">
            <Link href="/pay/verify" className="card flex flex-col items-start gap-2 p-4 hover:border-violet-200">
              <IdCard className="h-5 w-5 text-violet-600" />
              <span className="text-[13px] font-semibold text-heading">Verify identity</span>
              <span className="text-[11px] text-muted">Raise your limit</span>
            </Link>
            <Link href="/pay/help" className="card flex flex-col items-start gap-2 p-4 hover:border-violet-200">
              <Book className="h-5 w-5 text-violet-600" />
              <span className="text-[13px] font-semibold text-heading">Help centre</span>
              <span className="text-[11px] text-muted">Fees, refunds, timing</span>
            </Link>
          </div>

          <Card className="p-4">
            <h2 className="flex items-center gap-2 text-[15px] font-semibold text-heading"><Chat className="h-4 w-4 text-violet-600" />Raise a ticket</h2>
            {sent ? (
              <p className="mt-2 text-[13px] text-success">Ticket raised. Our compliance team reviews disputes within one business day.</p>
            ) : null}
            <form className="mt-3 space-y-3" onSubmit={async (e) => {
              e.preventDefault(); setBusy(true); setError(""); setSent(false);
              try {
                await api("/support/tickets", { method: "POST", audience: "cowriepay", body: { subject, body, transactionReference: reference || undefined } });
                setSubject(""); setBody(""); setReference(""); setSent(true); await load();
              } catch (err) { setError(err instanceof Error ? err.message : "Could not raise that ticket."); }
              finally { setBusy(false); }
            }}>
              <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="What is this about?" aria-label="Subject" className={inputClass} required minLength={4} />
              <textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="Tell us what happened" aria-label="Details" rows={3} className={cx(inputClass, "resize-none")} required minLength={10} />
              <input value={reference} onChange={(e) => setReference(e.target.value)} placeholder="Transfer reference (optional), e.g. CWR-A31C22" aria-label="Transfer reference" className={cx(inputClass, "font-mono text-[12px]")} />
              {error ? <ErrorText>{error}</ErrorText> : null}
              <Button type="submit" full loading={busy}>Send</Button>
            </form>
          </Card>

          {tickets && tickets.length > 0 ? (
            <Card className="divide-y divide-line">
              <p className="px-4 pt-4 text-[13px] font-semibold text-heading">Your tickets</p>
              {tickets.map((t) => (
                <div key={t.id} className="px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <p className="text-[13px] font-medium text-heading">{t.subject}</p>
                    <Badge tone={t.status === "RESOLVED" ? "success" : t.status === "ESCALATED" ? "warning" : "progress"}>{t.status}</Badge>
                  </div>
                  <p className="mt-1 text-[11px] text-subtle">{relativeTime(t.createdAt)}</p>
                  {t.resolution ? <p className="mt-1.5 text-[12px] text-muted">{t.resolution}</p> : null}
                </div>
              ))}
            </Card>
          ) : null}

          <Button variant="ghost" full onClick={signOut}>Sign out</Button>
        </div>
      </div>
      <TabBar />
    </div>
  );
}
