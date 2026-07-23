"use client";

/**
 * CowriePay — Login (screen 01).
 *
 * SRS 3.1: "Login: six-digit PIN with a randomized keypad."
 *
 * The randomisation is a shoulder-surfing defence. On a fixed keypad the shape
 * a thumb traces is the same every time, so anyone watching once can reproduce
 * the PIN without ever seeing a digit. Reshuffling the layout on each attempt
 * makes the gesture carry no information.
 *
 * It costs the user something — the keys are not where muscle memory expects —
 * so the screen says what it is doing rather than leaving people to think the
 * app is broken.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CowrieMark } from "@/components/brand";
import { Backspace, ChevronLeft, Info, ShieldCheck } from "@/components/icons";
import { Button, ErrorText, cx, inputClass } from "@/components/ui";
import { useSession } from "@/components/pay/session";

const PIN_LENGTH = 6;
const REMEMBERED_PHONE = "cowrie.pay.phone";

/** Fisher-Yates. Unbiased, unlike sort(() => Math.random() - 0.5). */
function shuffled(): number[] {
  const digits = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9];
  for (let i = digits.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1));
    [digits[i], digits[j]] = [digits[j], digits[i]];
  }
  return digits;
}

export default function LoginPage() {
  const router = useRouter();
  const { signIn, user, loading } = useSession();

  const [phone, setPhone] = useState<string | null>(null);
  const [phoneDraft, setPhoneDraft] = useState("+2348012345678");
  const [pin, setPin] = useState("");
  const [keys, setKeys] = useState<number[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");

  // Shuffle on the client only. Doing it during render would produce different
  // markup on the server and the client and trip a hydration mismatch.
  useEffect(() => setKeys(shuffled()), []);

  useEffect(() => {
    const remembered = window.localStorage.getItem(REMEMBERED_PHONE);
    if (remembered) {
      setPhone(remembered);
      setName(window.localStorage.getItem("cowrie.pay.name") ?? "");
    }
  }, []);

  useEffect(() => {
    if (!loading && user) router.replace("/pay");
  }, [loading, user, router]);

  const submit = useCallback(
    async (candidate: string) => {
      if (!phone) return;
      setBusy(true);
      setError("");
      try {
        await signIn(phone, candidate);
        router.replace("/pay");
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not sign you in.");
        setPin("");
        // A fresh layout for the retry, so a watcher gets nothing from the
        // second attempt either.
        setKeys(shuffled());
        setBusy(false);
      }
    },
    [phone, signIn, router],
  );

  const press = useCallback(
    (digit: number) => {
      if (busy) return;
      setError("");
      setPin((current) => {
        if (current.length >= PIN_LENGTH) return current;
        const next = current + String(digit);
        if (next.length === PIN_LENGTH) void submit(next);
        return next;
      });
    },
    [busy, submit],
  );

  const back = useCallback(() => {
    setError("");
    setPin((current) => current.slice(0, -1));
  }, []);

  // NFR 7: the keypad must be operable from a physical keyboard too.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!phone || busy) return;
      if (/^[0-9]$/.test(event.key)) {
        event.preventDefault();
        press(Number(event.key));
      } else if (event.key === "Backspace") {
        event.preventDefault();
        back();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [phone, busy, press, back]);

  const grid = useMemo(() => keys.slice(0, 9), [keys]);
  const lastDigit = keys[9];

  // ---- phone step: only shown when no number is remembered ---------------
  if (!phone) {
    return (
      <div className="flex flex-1 flex-col px-7 pb-10 pt-10">
        <div className="flex flex-1 flex-col items-center justify-center">
          <CowrieMark className="h-10 w-10 text-violet-600" />
          <h1 className="mt-4 text-xl font-bold tracking-tight text-heading">Welcome to Cowrie</h1>
          <p className="mt-1.5 text-center text-sm text-muted">
            Enter the phone number on your account
          </p>

          <form
            className="mt-8 w-full space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              const cleaned = phoneDraft.replace(/\s/g, "");
              if (!cleaned.startsWith("+")) {
                setError("Use the international format, e.g. +2348012345678");
                return;
              }
              window.localStorage.setItem(REMEMBERED_PHONE, cleaned);
              setPhone(cleaned);
              setError("");
            }}
          >
            <div className="space-y-1.5">
              <label htmlFor="phone" className="block text-[13px] font-medium text-ink">
                Phone number
              </label>
              <input
                id="phone"
                type="tel"
                inputMode="tel"
                autoComplete="tel"
                value={phoneDraft}
                onChange={(event) => setPhoneDraft(event.target.value)}
                className={cx(inputClass, "text-center text-base tracking-wide")}
              />
            </div>
            {error ? <ErrorText>{error}</ErrorText> : null}
            <Button type="submit" size="lg" full>
              Continue
            </Button>
          </form>


        </div>
      </div>
    );
  }

  // ---- PIN step ----------------------------------------------------------
  return (
    <div className="flex flex-1 flex-col px-7 pb-8 pt-6">
      <button
        type="button"
        onClick={() => {
          window.localStorage.removeItem(REMEMBERED_PHONE);
          setPhone(null);
          setPin("");
        }}
        className="mb-2 -ml-2 inline-flex h-9 w-9 items-center justify-center rounded-full text-muted hover:bg-canvas"
        aria-label="Use a different phone number"
      >
        <ChevronLeft />
      </button>

      <div className="flex flex-col items-center">
        <CowrieMark className="h-9 w-9 text-violet-600" />
        <p className="mt-2 text-[15px] font-semibold tracking-tight text-violet-600">Cowrie</p>

        <h1 className="mt-7 text-xl font-bold tracking-tight text-heading">
          {name ? `Welcome back, ${name}` : "Welcome back"}
        </h1>
        <p className="mt-1.5 text-[13px] text-muted">Enter your 6-digit PIN to continue</p>

        {/* PIN dots. The input is described to assistive tech by its label and
            a live count, since the dots themselves carry no text. */}
        <div
          className="mt-7 flex items-center gap-3.5"
          role="img"
          aria-label={`PIN entry, ${pin.length} of ${PIN_LENGTH} digits entered`}
        >
          {Array.from({ length: PIN_LENGTH }).map((_, index) => (
            <span
              key={index}
              className={cx(
                "h-3.5 w-3.5 rounded-full border-2 transition-colors",
                index < pin.length
                  ? "border-violet-600 bg-violet-600"
                  : "border-line-strong bg-transparent",
              )}
            />
          ))}
        </div>

        <p className="mt-5 inline-flex items-center gap-1.5 text-[12px] text-subtle">
          <ShieldCheck className="h-3.5 w-3.5" />
          Shuffled keypad
          <span
            className="inline-flex"
            title="The keys move each time so nobody can learn your PIN by watching the shape your thumb makes."
          >
            <Info className="h-3.5 w-3.5" />
          </span>
        </p>

        {error ? (
          <div className="mt-4">
            <ErrorText>{error}</ErrorText>
          </div>
        ) : null}
      </div>

      {/* Keypad */}
      <div className="mt-7 grid grid-cols-3 gap-3">
        {grid.map((digit) => (
          <Key key={digit} onClick={() => press(digit)} disabled={busy}>
            {digit}
          </Key>
        ))}

        <span aria-hidden="true" />

        <Key onClick={() => press(lastDigit)} disabled={busy}>
          {lastDigit}
        </Key>

        <Key onClick={back} disabled={busy || pin.length === 0} label="Delete last digit">
          <Backspace className="h-6 w-6" />
        </Key>
      </div>

      <div className="mt-auto pt-6 text-center">
        <button
          type="button"
          className="text-[13px] font-semibold text-violet-600 hover:text-violet-700"
          onClick={() => setError("Call +234 700 COWRIE to reset your PIN.")}
        >
          Forgot PIN?
        </button>
      </div>
    </div>
  );
}

function Key({
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
        "flex h-[58px] items-center justify-center rounded-2xl border border-line bg-white",
        "text-2xl font-semibold text-heading transition-colors",
        "hover:border-violet-200 hover:bg-violet-50 active:bg-violet-100",
        "disabled:opacity-40",
      )}
    >
      {children}
    </button>
  );
}
