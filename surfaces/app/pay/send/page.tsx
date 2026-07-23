"use client";

/**
 * CowriePay — Send money (screens 03 and 04).
 *
 * SRS 3.1: "Send/Quote Confirmation: beneficiary, amount, itemized fees
 * (Foreign Exchange, Gas, Liquidity Spread, Cowrie fee), and PIN confirmation."
 *
 * NFR 6: "Sending money to a recipient takes 3 taps or 4 steps. Every quote
 * shows each fee on its own line ... The interface never bundles fees into a
 * single total."
 *
 * The four steps are: pick recipient, enter amount, review the quote, confirm
 * with the PIN. All four fee components are rendered as separate rows, and the
 * total is shown *in addition to* them rather than instead of them.
 *
 * Every figure on this screen comes from the API. Nothing is computed in the
 * browser — if the client and the server disagreed about a fee, the number the
 * user agreed to would not be the number they were charged.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Flag } from "@/components/brand";
import {
  Backspace,
  Bolt,
  ChevronDown,
  ChevronLeft,
  Close,
  Lock,
  Refresh,
  Scan,
  User,
} from "@/components/icons";
import { Avatar, Button, ErrorText, Notice, Skeleton, cx, inputClass } from "@/components/ui";
import { useRequireSession } from "@/components/pay/session";
import { api, type Quote, type Transfer } from "@/lib/api";
import { avatarTone, groupDigits, initials, money, prettyMsisdn } from "@/lib/format";

const PIN_LENGTH = 6;

function shuffled(): number[] {
  const digits = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
  for (let i = digits.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [digits[i], digits[j]] = [digits[j], digits[i]];
  }
  return digits;
}

type Beneficiary = { name: string; msisdn: string };

export default function SendPage() {
  const router = useRouter();
  const { user, loading } = useRequireSession();

  const [step, setStep] = useState<1 | 2>(1);

  // step 1
  const [msisdn, setMsisdn] = useState("");
  const [recipientName, setRecipientName] = useState("");
  const [amount, setAmount] = useState("");
  const [recent, setRecent] = useState<Beneficiary[]>([]);
  const [quote, setQuote] = useState<Quote | null>(null);
  const [quoting, setQuoting] = useState(false);

  // step 2
  const [transfer, setTransfer] = useState<Transfer | null>(null);
  const [pin, setPin] = useState("");
  const [keys, setKeys] = useState<number[]>([]);
  const [stepUpCode, setStepUpCode] = useState("");
  const [busy, setBusy] = useState(false);

  const [error, setError] = useState("");
  const quoteTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => setKeys(shuffled()), []);

  // ---- recent beneficiaries, for the quick-pick row --------------------
  useEffect(() => {
    if (!user) return;
    void (async () => {
      try {
        const result = await api<{ transfers: Transfer[] }>("/transfers?limit=25", {
          audience: "cowriepay",
        });
        const seen = new Map<string, Beneficiary>();
        for (const item of result.transfers) {
          if (item.recipient.msisdn && !seen.has(item.recipient.msisdn)) {
            seen.set(item.recipient.msisdn, {
              name: item.recipient.name,
              msisdn: item.recipient.msisdn,
            });
          }
        }
        setRecent([...seen.values()].slice(0, 4));
      } catch {
        setRecent([]);
      }
    })();
  }, [user]);

  // ---- live quote as the amount changes (FR 2.1) -----------------------
  const requestQuote = useCallback(async (value: string) => {
    const numeric = value.replace(/,/g, "");
    if (!numeric || Number(numeric) <= 0) {
      setQuote(null);
      return;
    }
    setQuoting(true);
    try {
      const result = await api<Quote>("/quotes", {
        method: "POST",
        audience: "cowriepay",
        body: { amount: numeric },
      });
      setQuote(result);
      setError("");
    } catch (err) {
      setQuote(null);
      setError(err instanceof Error ? err.message : "Could not price that amount.");
    } finally {
      setQuoting(false);
    }
  }, []);

  useEffect(() => {
    if (quoteTimer.current) clearTimeout(quoteTimer.current);
    // Debounced: a quote per keystroke would be a request per digit typed.
    quoteTimer.current = setTimeout(() => void requestQuote(amount), 350);
    return () => {
      if (quoteTimer.current) clearTimeout(quoteTimer.current);
    };
  }, [amount, requestQuote]);

  // ---- the 60 second lock, counted down in view (FR 2.1) ---------------
  const [secondsLeft, setSecondsLeft] = useState(0);
  useEffect(() => {
    if (!quote) return;
    setSecondsLeft(quote.secondsRemaining);
    const id = setInterval(() => setSecondsLeft((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(id);
  }, [quote]);

  // A lapsed quote must not be confirmable. Re-price rather than let the user
  // agree to a rate that no longer holds.
  useEffect(() => {
    if (step === 2 && secondsLeft === 0 && quote) {
      setError("That quote expired. Here is the current rate.");
      setStep(1);
      void requestQuote(amount);
    }
  }, [step, secondsLeft, quote, amount, requestQuote]);

  const canContinue = Boolean(
    quote && msisdn.replace(/\s/g, "").startsWith("+254") && msisdn.replace(/\s/g, "").length >= 12,
  );

  // ---- step 1 -> 2: create the transfer --------------------------------
  const createTransfer = useCallback(async () => {
    if (!quote) return;
    setBusy(true);
    setError("");
    try {
      const created = await api<Transfer>("/transfers", {
        method: "POST",
        audience: "cowriepay",
        body: {
          quoteId: quote.id,
          recipientName: recipientName.trim() || "Recipient",
          recipientMsisdn: msisdn.replace(/\s/g, ""),
          scenario: "HAPPY",
        },
      });
      setTransfer(created);
      // FR 2.2: a large transfer needs a second factor as well as the PIN. The
      // code is returned by the API because this build has no SMS provider.
      if (created.stepUp?.required && created.stepUp.demoCode) {
        setStepUpCode(created.stepUp.demoCode);
      }
      setStep(2);
      setKeys(shuffled());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start that transfer.");
    } finally {
      setBusy(false);
    }
  }, [quote, msisdn, recipientName]);

  // ---- confirm ---------------------------------------------------------
  const confirm = useCallback(
    async (candidate: string) => {
      if (!transfer) return;
      setBusy(true);
      setError("");
      try {
        await api(`/transfers/${transfer.id}/confirm`, {
          method: "POST",
          audience: "cowriepay",
          body: {
            pin: candidate,
            stepUpChallengeId: transfer.stepUp?.challengeId,
            stepUpCode: transfer.stepUp?.required ? stepUpCode : undefined,
          },
        });
        router.replace(`/pay/status/${transfer.id}`);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not confirm.");
        setPin("");
        setKeys(shuffled());
        setBusy(false);
      }
    },
    [transfer, stepUpCode, router],
  );

  const pressKey = useCallback(
    (digit: number) => {
      if (busy) return;
      setError("");
      setPin((current) => {
        if (current.length >= PIN_LENGTH) return current;
        const next = current + String(digit);
        if (next.length === PIN_LENGTH) void confirm(next);
        return next;
      });
    },
    [busy, confirm],
  );

  if (loading || !user) {
    return (
      <div className="space-y-4 px-5 pt-6">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="h-20 w-full rounded-card" />
        <Skeleton className="h-32 w-full rounded-card" />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* ---- header ---- */}
      <header className="shrink-0 px-5 pb-3 pt-3">
        <div className="flex items-center justify-between">
          <button
            type="button"
            onClick={() => (step === 2 ? setStep(1) : router.push("/pay"))}
            className="flex h-9 w-9 items-center justify-center rounded-full text-muted transition-colors hover:bg-canvas"
            aria-label={step === 2 ? "Back to amount" : "Back to home"}
          >
            <ChevronLeft />
          </button>

          <h1 className="text-[15px] font-semibold text-heading">
            {step === 1 ? "Send money" : "Confirm transfer"}
          </h1>

          {step === 1 ? (
            <Link
              href="/pay"
              className="flex h-9 w-9 items-center justify-center rounded-full text-muted transition-colors hover:bg-canvas"
              aria-label="Cancel"
            >
              <Close />
            </Link>
          ) : (
            <span className="h-9 w-9" />
          )}
        </div>

        {/* progress */}
        <div className="mt-2 flex items-center gap-2">
          <span className="h-1 w-8 rounded-full bg-violet-600" />
          <span className={cx("h-1 w-8 rounded-full", step === 2 ? "bg-violet-600" : "bg-line")} />
          <span className="ml-auto text-[11px] text-subtle">Step {step} of 2</span>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin px-5 pb-4">
        {step === 1 ? (
          <StepOne
            user={user}
            msisdn={msisdn}
            setMsisdn={setMsisdn}
            recipientName={recipientName}
            setRecipientName={setRecipientName}
            amount={amount}
            setAmount={setAmount}
            recent={recent}
            quote={quote}
            quoting={quoting}
            secondsLeft={secondsLeft}
            error={error}
          />
        ) : (
          <StepTwo
            transfer={transfer}
            quote={quote}
            pin={pin}
            keys={keys}
            onKey={pressKey}
            onBackspace={() => setPin((p) => p.slice(0, -1))}
            stepUpCode={stepUpCode}
            setStepUpCode={setStepUpCode}
            busy={busy}
            error={error}
          />
        )}
      </div>

      {/* ---- footer action ---- */}
      <div className="shrink-0 border-t border-line bg-white px-5 pb-5 pt-4">
        {step === 1 ? (
          <Button size="lg" full disabled={!canContinue || busy} loading={busy} onClick={createTransfer}>
            Continue
          </Button>
        ) : (
          <Button
            size="lg"
            full
            disabled={pin.length !== PIN_LENGTH || busy}
            loading={busy}
            onClick={() => void confirm(pin)}
          >
            <Lock className="h-4 w-4" />
            Confirm and send
          </Button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 1 — recipient and amount
// ---------------------------------------------------------------------------

function StepOne({
  user,
  msisdn,
  setMsisdn,
  recipientName,
  setRecipientName,
  amount,
  setAmount,
  recent,
  quote,
  quoting,
  secondsLeft,
  error,
}: {
  user: { ngnBalance: string };
  msisdn: string;
  setMsisdn: (v: string) => void;
  recipientName: string;
  setRecipientName: (v: string) => void;
  amount: string;
  setAmount: (v: string) => void;
  recent: Beneficiary[];
  quote: Quote | null;
  quoting: boolean;
  secondsLeft: number;
  error: string;
}) {
  return (
    <div className="space-y-5">
      {/* FROM */}
      <section>
        <p className="eyebrow mb-2">From</p>
        <div className="flex items-center gap-3 rounded-card border border-line bg-white px-3.5 py-3">
          <Flag country="NG" className="h-8 w-8" />
          <div className="min-w-0 flex-1">
            <p className="text-sm font-semibold text-heading">Naira wallet · NGN</p>
            <p className="text-[12px] text-muted tabular-nums">
              Balance · {money(user.ngnBalance, "NGN")}
            </p>
          </div>
          <ChevronDown className="h-4 w-4 shrink-0 text-subtle" />
        </div>
      </section>

      {/* RECIPIENT */}
      <section>
        <p className="eyebrow mb-2">Recipient</p>
        <div className="relative">
          <User className="pointer-events-none absolute left-3.5 top-1/2 h-[18px] w-[18px] -translate-y-1/2 text-subtle" />
          <input
            id="msisdn"
            type="tel"
            inputMode="tel"
            value={msisdn}
            onChange={(event) => setMsisdn(event.target.value)}
            placeholder="+254 712 345 678"
            aria-label="Recipient M-Pesa number"
            className={cx(inputClass, "pl-11 pr-11 tabular-nums")}
          />
          <span className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-violet-500">
            <Scan className="h-[18px] w-[18px]" />
          </span>
        </div>

        {msisdn && !msisdn.replace(/\s/g, "").startsWith("+254") ? (
          <p className="mt-1.5 text-[12px] text-warning">Kenyan M-Pesa numbers only (+254).</p>
        ) : null}

        {recent.length > 0 ? (
          <ul className="mt-3 flex gap-4">
            {recent.map((person) => {
              const active = person.msisdn === msisdn.replace(/\s/g, "");
              return (
                <li key={person.msisdn}>
                  <button
                    type="button"
                    onClick={() => {
                      setMsisdn(person.msisdn);
                      setRecipientName(person.name);
                    }}
                    className="flex w-14 flex-col items-center gap-1.5"
                    aria-pressed={active}
                  >
                    <Avatar
                      name={initials(person.name)}
                      tone={avatarTone(person.msisdn)}
                      size="md"
                      className={active ? "ring-2 ring-violet-600 ring-offset-2 rounded-full" : ""}
                    />
                    <span className="w-full truncate text-center text-[11px] text-muted">
                      {person.name.split(" ")[0]}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : null}

        {msisdn && !recipientName ? (
          <input
            type="text"
            value={recipientName}
            onChange={(event) => setRecipientName(event.target.value)}
            placeholder="Recipient's name"
            aria-label="Recipient's name"
            className={cx(inputClass, "mt-3")}
          />
        ) : null}
      </section>

      {/* YOU SEND */}
      <section>
        <p className="eyebrow mb-2">You send</p>
        <div className="rounded-card border border-line bg-white">
          <div className="flex items-center gap-3 px-3.5 py-3.5">
            <span className="text-[26px] font-bold text-heading">₦</span>
            <input
              type="text"
              inputMode="decimal"
              value={amount}
              onChange={(event) => setAmount(event.target.value.replace(/[^0-9.]/g, ""))}
              placeholder="0"
              aria-label="Amount to send in naira"
              className="w-full min-w-0 border-0 bg-transparent p-0 text-[26px] font-bold tabular-nums text-heading placeholder:text-line-strong focus:outline-none focus:ring-0"
            />
            <span className="inline-flex shrink-0 items-center gap-1.5 rounded-pill bg-canvas px-2.5 py-1.5 text-[12px] font-semibold text-ink">
              <Flag country="NG" className="h-4 w-4" />
              NGN
            </span>
          </div>

          <div className="divider" />

          <div className="flex items-center gap-3 px-3.5 py-3.5">
            <div className="min-w-0 flex-1">
              <p className="text-[11px] text-subtle">
                {recipientName ? `${recipientName.split(" ")[0]} receives` : "Recipient receives"}
              </p>
              <p className="mt-0.5 flex items-baseline gap-1.5">
                <span className="text-[13px] font-semibold text-muted">KES</span>
                {quoting && !quote ? (
                  <Skeleton className="h-6 w-24" />
                ) : (
                  <span className="text-[24px] font-bold tabular-nums text-heading">
                    {quote ? groupDigits(quote.destination.amount).whole : "0"}
                    <span className="text-[16px] text-muted">
                      .{quote ? groupDigits(quote.destination.amount).fraction : "00"}
                    </span>
                  </span>
                )}
              </p>
            </div>
            <span className="inline-flex shrink-0 items-center gap-1.5 rounded-pill bg-canvas px-2.5 py-1.5 text-[12px] font-semibold text-ink">
              <Flag country="KE" className="h-4 w-4" />
              KES
              <ChevronDown className="h-3 w-3 text-subtle" />
            </span>
          </div>
        </div>

        {quote ? (
          <p className="mt-2 flex items-center gap-1.5 text-[11px] italic text-subtle">
            <Refresh className="h-3 w-3" />
            1 NGN = {(1 / Number(quote.midMarketRate)).toFixed(4)} KES · refreshes in {secondsLeft}s
          </p>
        ) : null}

        {quote && !quote.withinLimit ? (
          <p className="mt-2 text-[12px] text-warning">Above your ${quote.limitUsd.toLocaleString()} limit.</p>
        ) : null}

        {error ? (
          <div className="mt-3">
            <ErrorText>{error}</ErrorText>
          </div>
        ) : null}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2 — confirm
// ---------------------------------------------------------------------------

function StepTwo({
  transfer,
  quote,
  pin,
  keys,
  onKey,
  onBackspace,
  stepUpCode,
  setStepUpCode,
  busy,
  error,
}: {
  transfer: Transfer | null;
  quote: Quote | null;
  pin: string;
  keys: number[];
  onKey: (d: number) => void;
  onBackspace: () => void;
  stepUpCode: string;
  setStepUpCode: (v: string) => void;
  busy: boolean;
  error: string;
}) {
  if (!transfer) return <Skeleton className="h-64 w-full rounded-card" />;

  const fees = transfer.fees;
  const rate = quote ? (1 / Number(quote.midMarketRate)).toFixed(4) : "—";
  // FR 3.3 / NFR 1: 12 confirmations at 2 second blocks, plus the ramps.
  const eta = 30;

  return (
    <div className="space-y-4">
      {/* recipient */}
      <div className="flex items-center gap-3 rounded-card border border-line bg-white px-3.5 py-3">
        <Avatar
          name={initials(transfer.recipient.name)}
          tone={avatarTone(transfer.recipient.msisdn)}
          size="md"
        />
        <div className="min-w-0 flex-1">
          <p className="text-[11px] text-subtle">Sending to</p>
          <p className="truncate text-sm font-semibold text-heading">{transfer.recipient.name}</p>
          <p className="truncate text-[12px] text-muted">
            Safaricom M-Pesa · {prettyMsisdn(transfer.recipient.msisdn)}
          </p>
        </div>
        <Flag country="KE" className="h-7 w-7" />
      </div>

      {/* amounts */}
      <div className="flex items-center gap-3 rounded-card border border-line bg-white px-3.5 py-3.5">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] text-subtle">You send</p>
          <p className="mt-0.5 truncate text-[19px] font-bold tabular-nums text-heading">
            {money(transfer.source.amount, "NGN", { decimals: false })}
          </p>
        </div>
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-violet-50 text-violet-600">
          <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M5 12h14M13 6l6 6-6 6" />
          </svg>
        </span>
        <div className="min-w-0 flex-1 text-right">
          <p className="text-[11px] text-subtle">
            {transfer.recipient.name.split(" ")[0]} receives
          </p>
          <p className="mt-0.5 truncate text-[19px] font-bold tabular-nums text-violet-600">
            KES {groupDigits(transfer.destination.amount).whole}.
            {groupDigits(transfer.destination.amount).fraction}
          </p>
        </div>
      </div>

      {/*
        Fee breakdown — NFR 6.
        Four components on four lines, plus the live rate. The total is shown as
        well as the parts, never instead of them.
      */}
      <div className="rounded-card border border-line bg-white px-3.5 py-3.5">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-heading">Fee breakdown</h2>
          <span className="rounded-pill bg-success-bg px-2 py-0.5 text-[11px] font-semibold text-success">
            {transfer.costPercent}% total
          </span>
        </div>

        <dl className="mt-3 space-y-2.5 text-[13px]">
          <Row label="Live FX rate" value={`1 NGN = ${rate} KES`} />
          <Row label="FX spread" value={money(fees.fxSpread, "NGN")} />
          <Row label="Network gas" value={money(fees.networkGas, "NGN")} />
          <Row label="LP spread" value={money(fees.liquiditySpread, "NGN")} />
          <Row label="Cowrie service fee" value={money(fees.cowrieFee, "NGN")} />
        </dl>

        <div className="divider my-3" />

        <div className="flex items-center justify-between">
          <span className="text-sm font-semibold text-heading">Total fee</span>
          <span className="text-sm font-bold tabular-nums text-heading">
            {money(fees.total, "NGN")} · {transfer.costPercent}%
          </span>
        </div>
      </div>

      {/* NFR 3 */}
      <p className="flex items-center gap-2 text-[12px] text-muted">
        <Bolt className="h-3.5 w-3.5 shrink-0 text-violet-600" />
        Arrives in ~{eta}s · auto-refunds in full if pending past 10 min
      </p>

      {/* FR 2.2 second factor */}
      {transfer.stepUp?.required ? (
        <div className="rounded-card border border-warning-ring bg-warning-bg px-3.5 py-3">
          <p className="text-[13px] font-semibold text-heading">Second factor required</p>
          <input
            type="text"
            inputMode="numeric"
            maxLength={6}
            value={stepUpCode}
            onChange={(event) => setStepUpCode(event.target.value.replace(/\D/g, ""))}
            aria-label="Six digit verification code"
            className={cx(inputClass, "mt-2.5 text-center text-lg tracking-[0.4em] tabular-nums")}
          />
        </div>
      ) : null}

      {/* PIN */}
      <div className="pt-1 text-center">
        <p className="text-[13px] text-muted">Enter your 6-digit PIN to confirm</p>
        <div
          className="mt-3 flex items-center justify-center gap-3"
          role="img"
          aria-label={`PIN entry, ${pin.length} of ${PIN_LENGTH} digits entered`}
        >
          {Array.from({ length: PIN_LENGTH }).map((_, index) => (
            <span
              key={index}
              className={cx(
                "h-3 w-3 rounded-full border-2 transition-colors",
                index < pin.length
                  ? "border-violet-600 bg-violet-600"
                  : "border-line-strong bg-transparent",
              )}
            />
          ))}
        </div>
      </div>

      {/* Shuffled keypad, same defence as the login screen. */}
      <div className="grid grid-cols-3 gap-2">
        {keys.slice(0, 9).map((digit) => (
          <MiniKey key={digit} onClick={() => onKey(digit)} disabled={busy}>
            {digit}
          </MiniKey>
        ))}
        <span aria-hidden="true" />
        <MiniKey onClick={() => onKey(keys[9])} disabled={busy}>
          {keys[9]}
        </MiniKey>
        <MiniKey onClick={onBackspace} disabled={busy || pin.length === 0} label="Delete last digit">
          <Backspace className="h-5 w-5" />
        </MiniKey>
      </div>

      {error ? <ErrorText>{error}</ErrorText> : null}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-muted">{label}</dt>
      <dd className="font-medium tabular-nums text-ink">{value}</dd>
    </div>
  );
}

function MiniKey({
  children,
  onClick,
  disabled,
  label,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      className={cx(
        "flex h-11 items-center justify-center rounded-xl border border-line bg-white",
        "text-lg font-semibold text-heading transition-colors",
        "hover:border-violet-200 hover:bg-violet-50 active:bg-violet-100 disabled:opacity-40",
      )}
    >
      {children}
    </button>
  );
}
