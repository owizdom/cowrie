"use client";

/**
 * CowriePay — create an account (FR 1.1).
 *
 * "Sign up with a phone number and email, verified by a one-time code before
 * the account is created."
 *
 * Two steps, and the ordering is the requirement: the details are held server
 * side against a challenge, and the account row is only written once the code
 * is verified. Abandoning the flow leaves nothing behind.
 */

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { CowrieMark } from "@/components/brand";
import { ChevronLeft } from "@/components/icons";
import { Button, ErrorText, cx, inputClass } from "@/components/ui";
import { setToken, api, type SessionUser } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [step, setStep] = useState<1 | 2>(1);

  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [email, setEmail] = useState("");
  const [pin, setPin] = useState("");
  const [confirmPin, setConfirmPin] = useState("");

  const [challengeId, setChallengeId] = useState("");
  const [code, setCode] = useState("");
  const [sentCode, setSentCode] = useState("");

  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const start = async () => {
    if (pin !== confirmPin) {
      setError("The PINs do not match.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api<{ challengeId: string; demoCode?: string }>("/auth/register/start", {
        method: "POST",
        body: { fullName, phone: phone.replace(/\s/g, ""), email, country: "NG", pin },
      });
      setChallengeId(result.challengeId);
      if (result.demoCode) setSentCode(result.demoCode);
      setStep(2);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start sign-up.");
    } finally {
      setBusy(false);
    }
  };

  const verify = async (value: string) => {
    setBusy(true);
    setError("");
    try {
      const result = await api<{ token: string; user: SessionUser }>("/auth/register/verify", {
        method: "POST",
        body: { challengeId, code: value },
      });
      setToken("cowriepay", result.token);
      window.localStorage.setItem("cowrie.pay.phone", result.user.phone);
      window.localStorage.setItem("cowrie.pay.name", result.user.fullName.split(" ")[0]);
      router.replace("/pay");
    } catch (err) {
      setError(err instanceof Error ? err.message : "That code was not accepted.");
      setCode("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-1 flex-col px-7 pb-8 pt-5">
      <button
        type="button"
        onClick={() => (step === 2 ? setStep(1) : router.push("/pay/login"))}
        className="-ml-2 mb-3 inline-flex h-9 w-9 items-center justify-center rounded-full text-muted hover:bg-canvas"
        aria-label="Back"
      >
        <ChevronLeft />
      </button>

      <CowrieMark className="h-8 w-8 text-violet-600" />

      {step === 1 ? (
        <form
          className="mt-5 space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void start();
          }}
        >
          <div>
            <h1 className="text-xl font-bold tracking-tight text-heading">Create your account</h1>
            <p className="mt-1 text-[13px] text-muted">Takes about a minute.</p>
          </div>

          <Field label="Full name" id="name">
            <input id="name" value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" required minLength={2} className={inputClass} />
          </Field>

          <Field label="Phone number" id="phone">
            <input id="phone" type="tel" inputMode="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+234 801 234 5678" autoComplete="tel" required className={cx(inputClass, "tabular-nums")} />
          </Field>

          <Field label="Email" id="email">
            <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required className={inputClass} />
          </Field>

          <div className="grid grid-cols-2 gap-3">
            <Field label="6-digit PIN" id="pin">
              <input id="pin" type="password" inputMode="numeric" maxLength={6} value={pin} onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))} required className={cx(inputClass, "text-center tracking-[0.3em] tabular-nums")} />
            </Field>
            <Field label="Confirm PIN" id="pin2">
              <input id="pin2" type="password" inputMode="numeric" maxLength={6} value={confirmPin} onChange={(e) => setConfirmPin(e.target.value.replace(/\D/g, ""))} required className={cx(inputClass, "text-center tracking-[0.3em] tabular-nums")} />
            </Field>
          </div>

          {error ? <ErrorText>{error}</ErrorText> : null}

          <Button type="submit" size="lg" full loading={busy} disabled={pin.length !== 6 || confirmPin.length !== 6}>
            Continue
          </Button>

          <p className="text-center text-[13px] text-muted">
            Already have an account?{" "}
            <Link href="/pay/login" className="font-semibold text-violet-600">Sign in</Link>
          </p>
        </form>
      ) : (
        <form
          className="mt-5 space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            void verify(code);
          }}
        >
          <div>
            <h1 className="text-xl font-bold tracking-tight text-heading">Enter the code</h1>
            <p className="mt-1 text-[13px] text-muted">Sent to {phone}</p>
          </div>

          <input
            value={code}
            onChange={(event) => {
              const next = event.target.value.replace(/\D/g, "").slice(0, 6);
              setCode(next);
              if (next.length === 6) void verify(next);
            }}
            inputMode="numeric"
            maxLength={6}
            autoFocus
            aria-label="Six digit code"
            className={cx(inputClass, "text-center text-2xl tracking-[0.5em] tabular-nums")}
          />

          {sentCode ? (
            <button
              type="button"
              onClick={() => { setCode(sentCode); void verify(sentCode); }}
              className="w-full text-center text-[12px] text-subtle hover:text-muted"
            >
              Use {sentCode}
            </button>
          ) : null}

          {error ? <ErrorText>{error}</ErrorText> : null}

          <Button type="submit" size="lg" full loading={busy} disabled={code.length !== 6}>
            Create account
          </Button>
        </form>
      )}
    </div>
  );
}

function Field({ label, id, children }: { label: string; id: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-[13px] font-medium text-ink">{label}</label>
      {children}
    </div>
  );
}
