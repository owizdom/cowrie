"use client";

/**
 * Shared primitives.
 *
 * SRS 3.1 requires all six surfaces to use the same system. These are the
 * pieces that enforce it: if a button, badge or card appears anywhere in the
 * product, it comes from here.
 *
 * Accessibility (NFR 7) is built into the primitives rather than left to each
 * screen — an icon-only button will not compile without a label, focus rings
 * come from the base layer, and every status colour is paired with a word so
 * the meaning does not rest on hue alone.
 */

import { useEffect, useRef, useState } from "react";
import { Check, Copy, Info } from "./icons";
import type { StateTone } from "@/lib/format";
import { TONE_CLASSES, TONE_DOT } from "@/lib/format";

export function cx(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

type ButtonProps = {
  variant?: "primary" | "secondary" | "ghost" | "outline" | "danger";
  size?: "sm" | "md" | "lg";
  full?: boolean;
  loading?: boolean;
  children: React.ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>;

const BUTTON_VARIANTS: Record<string, string> = {
  primary:
    "bg-violet-600 text-white hover:bg-violet-700 active:bg-violet-800 disabled:bg-violet-300",
  secondary:
    "bg-violet-50 text-violet-700 hover:bg-violet-100 active:bg-violet-200 disabled:text-violet-300",
  outline:
    "border border-violet-300 text-violet-700 bg-white hover:bg-violet-50 active:bg-violet-100 disabled:text-violet-300 disabled:border-line",
  ghost: "text-muted hover:bg-canvas hover:text-ink active:bg-line",
  danger: "bg-danger text-white hover:brightness-95 active:brightness-90",
};

const BUTTON_SIZES: Record<string, string> = {
  sm: "h-9 px-3.5 text-[13px] rounded-field gap-1.5",
  md: "h-11 px-5 text-sm rounded-field gap-2",
  lg: "h-14 px-6 text-[15px] rounded-pill gap-2",
};

export function Button({
  variant = "primary",
  size = "md",
  full,
  loading,
  children,
  className,
  disabled,
  ...rest
}: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cx(
        "inline-flex items-center justify-center font-semibold transition-colors",
        "disabled:cursor-not-allowed",
        BUTTON_VARIANTS[variant],
        BUTTON_SIZES[size],
        full && "w-full",
        className,
      )}
    >
      {loading ? <Spinner className="h-4 w-4" /> : null}
      {children}
    </button>
  );
}

export function Spinner({ className = "h-5 w-5" }: { className?: string }) {
  return (
    <svg className={cx("animate-spin", className)} viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" fill="none" opacity="0.22" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Surfaces
// ---------------------------------------------------------------------------

export function Card({
  className,
  children,
  ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div {...rest} className={cx("card", className)}>
      {children}
    </div>
  );
}

export function CardHeader({
  title,
  subtitle,
  action,
  className,
}: {
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cx("flex items-start justify-between gap-4 px-5 pt-5", className)}>
      <div className="min-w-0">
        <h2 className="text-[15px] font-semibold text-heading">{title}</h2>
        {subtitle ? <p className="mt-0.5 text-[13px] text-muted">{subtitle}</p> : null}
      </div>
      {action ? <div className="flex shrink-0 items-center gap-2">{action}</div> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Badges, pills, chips
// ---------------------------------------------------------------------------

export function Badge({
  tone = "neutral",
  dot,
  children,
  className,
}: {
  tone?: StateTone;
  dot?: boolean;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cx(
        "inline-flex items-center gap-1.5 rounded-pill px-2.5 py-1 text-[11px] font-semibold ring-1 ring-inset",
        TONE_CLASSES[tone],
        className,
      )}
    >
      {dot ? <span className={cx("h-1.5 w-1.5 rounded-full", TONE_DOT[tone])} /> : null}
      {children}
    </span>
  );
}

/**
 * A filter chip.
 *
 * `pressed` drives aria-pressed as well as the styling, so a screen reader
 * announces which filters are on — colour alone would not (NFR 7).
 */
export function Chip({
  pressed,
  onClick,
  children,
  tone = "violet",
}: {
  pressed: boolean;
  onClick: () => void;
  children: React.ReactNode;
  tone?: "violet" | "dark";
}) {
  const activeClass =
    tone === "dark" ? "bg-heading text-white" : "bg-violet-600 text-white";
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={pressed}
      className={cx(
        "h-8 rounded-pill px-3.5 text-[13px] font-medium transition-colors",
        pressed
          ? activeClass
          : "border border-line bg-white text-muted hover:border-line-strong hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Avatar
// ---------------------------------------------------------------------------

export function Avatar({
  name,
  tone,
  size = "md",
  flag,
  className,
}: {
  name: string;
  tone: string;
  size?: "xs" | "sm" | "md" | "lg";
  flag?: React.ReactNode;
  className?: string;
}) {
  const sizes = {
    xs: "h-7 w-7 text-[10px]",
    sm: "h-9 w-9 text-[11px]",
    md: "h-10 w-10 text-xs",
    lg: "h-12 w-12 text-sm",
  };
  return (
    <span className={cx("relative inline-flex shrink-0", className)}>
      <span
        className={cx(
          "inline-flex items-center justify-center rounded-full font-semibold",
          sizes[size],
          tone,
        )}
        aria-hidden="true"
      >
        {name}
      </span>
      {flag ? <span className="absolute -bottom-0.5 -right-0.5">{flag}</span> : null}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Copy to clipboard
// ---------------------------------------------------------------------------

export function CopyButton({
  value,
  label,
  className,
}: {
  value: string;
  label: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current); }, []);

  return (
    <button
      type="button"
      className={cx(
        "inline-flex h-7 w-7 items-center justify-center rounded-md text-subtle transition-colors hover:bg-canvas hover:text-ink",
        className,
      )}
      aria-label={copied ? `${label} copied` : `Copy ${label}`}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
        } catch {
          // Clipboard needs a secure context; without one the button simply
          // does nothing rather than throwing at the user.
          return;
        }
        setCopied(true);
        if (timer.current) clearTimeout(timer.current);
        timer.current = setTimeout(() => setCopied(false), 1600);
      }}
    >
      {copied ? <Check className="h-4 w-4 text-success" /> : <Copy className="h-4 w-4" />}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Notices
// ---------------------------------------------------------------------------

export function Notice({
  tone = "progress",
  icon,
  title,
  children,
  className,
}: {
  tone?: StateTone;
  icon?: React.ReactNode;
  title?: React.ReactNode;
  children?: React.ReactNode;
  className?: string;
}) {
  const bg = {
    progress: "bg-violet-50 border-violet-100",
    success: "bg-success-bg border-success-ring",
    warning: "bg-warning-bg border-warning-ring",
    danger: "bg-danger-bg border-danger-ring",
    neutral: "bg-canvas border-line",
  }[tone];

  const iconColor = {
    progress: "text-violet-600",
    success: "text-success",
    warning: "text-warning",
    danger: "text-danger",
    neutral: "text-muted",
  }[tone];

  return (
    <div className={cx("flex gap-3 rounded-field border p-3.5", bg, className)}>
      <span className={cx("mt-0.5 shrink-0", iconColor)}>
        {icon ?? <Info className="h-[18px] w-[18px]" />}
      </span>
      <div className="min-w-0 text-[13px]">
        {title ? <p className="font-semibold text-heading">{title}</p> : null}
        {children ? <div className="text-muted">{children}</div> : null}
      </div>
    </div>
  );
}

export function ErrorText({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="text-[13px] font-medium text-danger">
      {children}
    </p>
  );
}

export function EmptyState({
  title,
  children,
  icon,
}: {
  title: string;
  children?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center">
      {icon ? <span className="mb-3 text-subtle">{icon}</span> : null}
      <p className="text-sm font-semibold text-heading">{title}</p>
      {children ? <p className="mt-1 max-w-sm text-[13px] text-muted">{children}</p> : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Fields
// ---------------------------------------------------------------------------

export function Field({
  label,
  hint,
  error,
  children,
  htmlFor,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-[13px] font-medium text-ink">
        {label}
      </label>
      {children}
      {error ? <ErrorText>{error}</ErrorText> : null}
      {!error && hint ? <p className="text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

export const inputClass =
  "w-full rounded-field border border-line bg-white px-3.5 py-2.5 text-sm text-ink " +
  "placeholder:text-subtle transition-colors hover:border-line-strong " +
  "focus:border-violet-500 focus:outline-none focus:ring-2 focus:ring-violet-200";

// ---------------------------------------------------------------------------
// Sparkline
// ---------------------------------------------------------------------------

/**
 * The trend line on the admin stat cards.
 *
 * Decorative and aria-hidden: the figure it accompanies is already stated in
 * text, so a screen reader announcing a path would only add noise.
 */
export function Sparkline({
  points,
  className = "h-10 w-28",
}: {
  points: number[];
  className?: string;
}) {
  if (points.length < 2) return <span className={className} />;

  const width = 100;
  const height = 32;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;

  const coords = points.map((value, index) => {
    const x = (index / (points.length - 1)) * width;
    const y = height - ((value - min) / span) * (height - 4) - 2;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <polygon points={`0,${height} ${coords.join(" ")} ${width},${height}`} fill="url(#spark)" />
      <polyline
        points={coords.join(" ")}
        fill="none"
        stroke="#7C3AED"
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      <defs>
        <linearGradient id="spark" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#7C3AED" stopOpacity="0.22" />
          <stop offset="100%" stopColor="#7C3AED" stopOpacity="0" />
        </linearGradient>
      </defs>
    </svg>
  );
}

/** Larger filled area chart, used on the reserve panel. */
export function AreaChart({
  points,
  className = "h-28 w-full",
}: {
  points: number[];
  className?: string;
}) {
  if (points.length < 2) return <div className={className} />;

  const width = 320;
  const height = 90;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;

  const coords = points.map((value, index) => {
    const x = (index / (points.length - 1)) * width;
    const y = height - ((value - min) / span) * (height - 8) - 4;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      className={className}
      aria-hidden="true"
      focusable="false"
    >
      <polygon points={`0,${height} ${coords.join(" ")} ${width},${height}`} fill="url(#area)" />
      <polyline
        points={coords.join(" ")}
        fill="none"
        stroke="#7C3AED"
        strokeWidth="2"
        strokeLinejoin="round"
        vectorEffect="non-scaling-stroke"
      />
      <defs>
        <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#7C3AED" stopOpacity="0.24" />
          <stop offset="100%" stopColor="#7C3AED" stopOpacity="0.02" />
        </linearGradient>
      </defs>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Skeleton
// ---------------------------------------------------------------------------

export function Skeleton({ className }: { className?: string }) {
  return (
    <span
      className={cx("block animate-pulse rounded bg-line", className)}
      aria-hidden="true"
    />
  );
}

/**
 * Announces changes to assistive technology.
 *
 * The transfer status screen updates itself over a WebSocket; without a live
 * region a screen-reader user would hear nothing at all as the transfer moved
 * from debiting to settled.
 */
export function LiveRegion({ message }: { message: string }) {
  return (
    <p aria-live="polite" aria-atomic="true" className="sr-only">
      {message}
    </p>
  );
}
