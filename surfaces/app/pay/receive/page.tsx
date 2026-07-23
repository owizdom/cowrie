"use client";

/**
 * CowriePay — Receive and Top up (two of the three action keys in SRS 3.1).
 *
 * A new wallet holds nothing, so this is where money enters: link a bank
 * account through Mono, then pull from it. That is the same on-ramp FR 2.2
 * uses to fund a transfer, which is why linking has to come first.
 */

import { useCallback, useState } from "react";
import Link from "next/link";
import { ChevronLeft, Plus, Wallet } from "@/components/icons";
import { Button, Card, CopyButton, ErrorText, Skeleton, cx, inputClass } from "@/components/ui";
import { TabBar } from "@/components/pay/tab-bar";
import { useRequireSession } from "@/components/pay/session";
import { api } from "@/lib/api";
import { money, prettyMsisdn } from "@/lib/format";

const BANKS = [
  "Guaranty Trust Bank",
  "Access Bank",
  "Zenith Bank",
  "First Bank of Nigeria",
  "United Bank for Africa",
];

export default function ReceivePage() {
  const { user, loading, refresh } = useRequireSession();

  const [institution, setInstitution] = useState(BANKS[0]);
  const [accountNumber, setAccountNumber] = useState("");
  const [amount, setAmount] = useState("100000");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [done, setDone] = useState("");

  const link = useCallback(async () => {
    setBusy("link");
    setError("");
    setDone("");
    try {
      await api("/kyc/link-account", {
        method: "POST",
        audience: "cowriepay",
        body: { kind: "BANK", institution, accountNumber },
      });
      await refresh();
      setDone("Bank account linked.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not link that account.");
    } finally {
      setBusy("");
    }
  }, [institution, accountNumber, refresh]);

  const topUp = useCallback(async () => {
    setBusy("topup");
    setError("");
    setDone("");
    try {
      const result = await api<{ credited: string }>("/kyc/top-up", {
        method: "POST",
        audience: "cowriepay",
        body: { amount },
      });
      await refresh();
      setDone(`${money(result.credited, "NGN")} added.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not top up.");
    } finally {
      setBusy("");
    }
  }, [amount, refresh]);

  if (loading || !user) return <Skeleton className="m-5 h-64" />;

  const linked = Boolean(user.bankName);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto scroll-thin pb-4">
        <header className="flex items-center gap-2 px-5 pb-2 pt-3">
          <Link
            href="/pay"
            className="flex h-9 w-9 items-center justify-center rounded-full text-muted hover:bg-canvas"
            aria-label="Back to home"
          >
            <ChevronLeft />
          </Link>
          <h1 className="text-[15px] font-semibold text-heading">Receive & top up</h1>
        </header>

        <div className="space-y-4 px-5 pt-2">
          <Card className="p-5 text-center">
            <p className="eyebrow">Your Cowrie number</p>
            <p className="mt-2 text-[20px] font-bold tabular-nums text-heading">
              {prettyMsisdn(user.phone)}
            </p>
            <div className="mt-1 flex justify-center">
              <CopyButton value={user.phone} label="phone number" />
            </div>
          </Card>

          <Card className="p-5">
            <p className="flex items-center gap-2 text-[15px] font-semibold text-heading">
              <Wallet className="h-4 w-4 text-violet-600" />
              {linked ? "Top up" : "Link a bank account"}
            </p>

            {linked ? (
              <>
                <p className="mt-1 text-[12px] text-muted">
                  {user.bankName} · {user.bankAccountMasked}
                </p>

                <div className="mt-4 space-y-3">
                  <label className="block">
                    <span className="mb-1 block text-[12px] text-muted">Amount (NGN)</span>
                    <input
                      value={amount}
                      onChange={(event) => setAmount(event.target.value.replace(/[^0-9.]/g, ""))}
                      inputMode="decimal"
                      className={cx(inputClass, "text-lg font-semibold tabular-nums")}
                    />
                  </label>

                  <div className="flex flex-wrap gap-2">
                    {["50000", "100000", "250000"].map((preset) => (
                      <button
                        key={preset}
                        type="button"
                        onClick={() => setAmount(preset)}
                        className={cx(
                          "rounded-pill border px-3 py-1.5 text-[12px] font-medium transition-colors",
                          amount === preset
                            ? "border-violet-300 bg-violet-50 text-violet-700"
                            : "border-line text-muted hover:border-line-strong",
                        )}
                      >
                        {money(preset, "NGN", { decimals: false })}
                      </button>
                    ))}
                  </div>

                  <Button full loading={busy === "topup"} onClick={topUp}>
                    <Plus className="h-4 w-4" />
                    Add money
                  </Button>
                </div>
              </>
            ) : (
              <>
                <p className="mt-1 text-[12px] text-muted">
                  Funds are pulled from your bank through Mono.
                </p>

                <div className="mt-4 space-y-3">
                  <label className="block">
                    <span className="mb-1 block text-[12px] text-muted">Bank</span>
                    <select
                      value={institution}
                      onChange={(event) => setInstitution(event.target.value)}
                      className={inputClass}
                    >
                      {BANKS.map((bank) => (
                        <option key={bank}>{bank}</option>
                      ))}
                    </select>
                  </label>

                  <label className="block">
                    <span className="mb-1 block text-[12px] text-muted">Account number</span>
                    <input
                      value={accountNumber}
                      onChange={(event) => setAccountNumber(event.target.value.replace(/\D/g, ""))}
                      inputMode="numeric"
                      maxLength={10}
                      placeholder="0123456789"
                      className={cx(inputClass, "tabular-nums")}
                    />
                  </label>

                  <Button
                    full
                    loading={busy === "link"}
                    disabled={accountNumber.length < 10}
                    onClick={link}
                  >
                    Link account
                  </Button>
                </div>
              </>
            )}

            {error ? (
              <div className="mt-3">
                <ErrorText>{error}</ErrorText>
              </div>
            ) : null}
            {done ? <p className="mt-3 text-[13px] font-medium text-success">{done}</p> : null}

            <p className="mt-4 border-t border-line pt-3 text-[12px] text-muted">
              Balance ·{" "}
              <span className="font-semibold tabular-nums text-ink">
                {money(user.ngnBalance, "NGN")}
              </span>
            </p>
          </Card>
        </div>
      </div>

      <TabBar />
    </div>
  );
}
