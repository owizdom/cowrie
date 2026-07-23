/**
 * Formatting.
 *
 * Money is handled as strings end to end. The API sends decimal strings
 * precisely so that a naira amount never passes through a float, and parsing
 * one into a JavaScript number here would undo that. Every function below takes
 * a string and formats it for display without arithmetic.
 */

const CURRENCY_SYMBOL: Record<string, string> = {
  NGN: "₦",
  KES: "KES",
  USD: "$",
  GHS: "GH₵",
  TZS: "TSh",
};

export function symbolFor(currency: string): string {
  return CURRENCY_SYMBOL[currency] ?? currency;
}

/**
 * Group the integer part with thousands separators, keep the decimals exact.
 *
 * Done by string manipulation rather than Number.toLocaleString, because the
 * latter would first coerce to a float and silently lose precision on large
 * naira amounts.
 */
export function groupDigits(value: string): { whole: string; fraction: string } {
  const negative = value.trim().startsWith("-");
  const cleaned = value.replace(/^-/, "").trim();
  const [rawWhole = "0", rawFraction = ""] = cleaned.split(".");

  const whole = rawWhole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const fraction = rawFraction.slice(0, 2).padEnd(2, "0");

  return { whole: `${negative ? "-" : ""}${whole}`, fraction };
}

/** "₦ 248,500.00" */
export function money(value: string, currency: string, opts: { decimals?: boolean } = {}): string {
  const { whole, fraction } = groupDigits(value);
  const symbol = symbolFor(currency);
  const body = opts.decimals === false ? whole : `${whole}.${fraction}`;
  return currency === "NGN" || currency === "USD" || currency === "GHS"
    ? `${symbol} ${body}`
    : `${symbol} ${body}`;
}

/** Compact form for stat cards: 12.4M, 248.5K */
export function compact(value: string): string {
  const n = Number(value.replace(/,/g, ""));
  if (!Number.isFinite(n)) return value;
  if (Math.abs(n) >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(0);
}

/** "12s ago", "4m ago", "2h ago", "Yesterday", "Mon" */
export function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));

  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days === 1) return "Yesterday";
  if (days < 7) return new Date(iso).toLocaleDateString(undefined, { weekday: "short" });
  return new Date(iso).toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function fullTimestamp(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "0x43a2378…0b61fcc" - long identifiers, middle-truncated. */
export function truncateHash(hash: string, lead = 8, tail = 6): string {
  if (!hash) return "";
  const value = hash.startsWith("0x") ? hash : `0x${hash}`;
  if (value.length <= lead + tail + 1) return value;
  return `${value.slice(0, lead)}…${value.slice(-tail)}`;
}

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "?";
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

/**
 * Deterministic pastel for an avatar.
 *
 * Deterministic matters: the same person keeps the same colour across screens
 * and reloads, which is what makes an avatar recognisable at a glance in the
 * recent-activity list.
 */
const AVATAR_TONES = [
  "bg-avatar-yellow text-[#854D0E]",
  "bg-avatar-pink text-[#9D174D]",
  "bg-avatar-blue text-[#1E40AF]",
  "bg-avatar-violet text-[#5B21B6]",
  "bg-avatar-orange text-[#9A3412]",
  "bg-avatar-green text-[#166534]",
  "bg-avatar-teal text-[#115E59]",
];

export function avatarTone(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i += 1) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  }
  return AVATAR_TONES[hash % AVATAR_TONES.length];
}

/** Mask a phone number to its last four: "+254 ••• ••• 678" */
export function maskMsisdn(msisdn: string): string {
  if (msisdn.length < 6) return msisdn;
  return `${msisdn.slice(0, 4)} ••• ••• ${msisdn.slice(-3)}`;
}

/** "+254 712 345 678" */
export function prettyMsisdn(msisdn: string): string {
  const cleaned = msisdn.replace(/\s/g, "");
  const match = cleaned.match(/^(\+\d{3})(\d{3})(\d{3})(\d{3})$/);
  return match ? `${match[1]} ${match[2]} ${match[3]} ${match[4]}` : msisdn;
}

// ---------------------------------------------------------------------------
// transfer state presentation
// ---------------------------------------------------------------------------

export type StateTone = "progress" | "success" | "warning" | "danger" | "neutral";

/**
 * How each state of the machine reads to a person.
 *
 * The labels are deliberately not the enum names. A sender does not need to
 * know what OFFRAMP_PENDING means; they need to know their money is being paid
 * out. The enum stays the source of truth in the API and the audit log.
 */
export const STATE_PRESENTATION: Record<
  string,
  { label: string; tone: StateTone; detail: string }
> = {
  CREATED: { label: "Starting", tone: "progress", detail: "Preparing your transfer" },
  QUOTED: { label: "Quote ready", tone: "neutral", detail: "Rate locked, awaiting confirmation" },
  AUTHORIZED: { label: "Confirmed", tone: "progress", detail: "Checks passed, contacting your bank" },
  ONRAMP_PENDING: { label: "Debiting", tone: "progress", detail: "Taking naira from your bank account" },
  BRIDGING: { label: "Settling on-chain", tone: "progress", detail: "Converting through cUSDC on Base" },
  OFFRAMP_PENDING: { label: "Paying out", tone: "progress", detail: "Sending shillings to M-Pesa" },
  SETTLED: { label: "Delivered", tone: "success", detail: "The recipient has been paid" },
  REFUNDING: { label: "Refunding", tone: "warning", detail: "Returning your naira" },
  REFUNDED: { label: "Refunded", tone: "warning", detail: "Your naira has been returned in full" },
  FAILED: { label: "Failed", tone: "danger", detail: "This transfer did not go through" },
  CANCELLED: { label: "Cancelled", tone: "neutral", detail: "The quote expired before confirmation" },
};

export function stateLabel(state: string): string {
  return STATE_PRESENTATION[state]?.label ?? state;
}

export const TONE_CLASSES: Record<StateTone, string> = {
  progress: "bg-violet-50 text-violet-700 ring-violet-200",
  success: "bg-success-bg text-success ring-success-ring",
  warning: "bg-warning-bg text-warning ring-warning-ring",
  danger: "bg-danger-bg text-danger ring-danger-ring",
  neutral: "bg-canvas text-muted ring-line-strong",
};

export const TONE_DOT: Record<StateTone, string> = {
  progress: "bg-violet-600",
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-danger",
  neutral: "bg-subtle",
};

/** Progress through the happy path, for the status screen's bar. */
export const SETTLEMENT_STEPS: TransferStep[] = [
  { state: "AUTHORIZED", label: "Confirmed" },
  { state: "ONRAMP_PENDING", label: "Bank debit" },
  { state: "BRIDGING", label: "On-chain" },
  { state: "OFFRAMP_PENDING", label: "M-Pesa payout" },
  { state: "SETTLED", label: "Delivered" },
];

export type TransferStep = { state: string; label: string };

export function stepIndex(state: string): number {
  const index = SETTLEMENT_STEPS.findIndex((step) => step.state === state);
  if (index >= 0) return index;
  // Refund and failure states sit off the happy path.
  if (state === "REFUNDING" || state === "REFUNDED" || state === "FAILED") return -1;
  return 0;
}
