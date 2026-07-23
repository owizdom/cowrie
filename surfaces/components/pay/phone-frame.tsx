"use client";

/**
 * Device frame for desktop viewing.
 *
 * Below `sm` the app fills the viewport, exactly as an installed PWA does on
 * Android 8+ or iOS 14+. At `sm` and above it sits inside a phone frame with a
 * status bar, matching the approved mockups.
 *
 * The frame is decorative and hidden from assistive technology; the app inside
 * is the real document.
 */

import { useEffect, useState } from "react";

export function PhoneFrame({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-canvas sm:grid-lines sm:flex sm:items-center sm:justify-center sm:py-10">
      <div
        className={
          "relative flex min-h-screen w-full flex-col overflow-hidden bg-white " +
          "sm:min-h-0 sm:h-[860px] sm:w-[400px] sm:rounded-[2.75rem] sm:border-[10px] " +
          "sm:border-heading sm:shadow-phone"
        }
      >
        <StatusBar />
        <main id="main" className="relative flex min-h-0 flex-1 flex-col">
          {children}
        </main>
        {/* Home indicator, on the framed presentation only. */}
        <div className="hidden justify-center pb-2 pt-1 sm:flex" aria-hidden="true">
          <span className="h-1 w-32 rounded-full bg-heading/25" />
        </div>
      </div>
    </div>
  );
}

/**
 * The iOS-style status bar from the mockups.
 *
 * Shows the real time rather than a frozen 9:41, because a demo recorded at
 * 14:20 that claims to be 9:41 is a small thing that quietly undermines
 * everything else on the screen.
 */
function StatusBar() {
  const [time, setTime] = useState<string>("");

  useEffect(() => {
    const tick = () =>
      setTime(
        new Date().toLocaleTimeString(undefined, {
          hour: "numeric",
          minute: "2-digit",
          hour12: false,
        }),
      );
    tick();
    const id = setInterval(tick, 20_000);
    return () => clearInterval(id);
  }, []);

  return (
    <div
      className="relative z-20 hidden shrink-0 items-center justify-between bg-white px-7 pb-1 pt-3 sm:flex"
      aria-hidden="true"
    >
      <span className="w-16 text-[13px] font-semibold tabular-nums text-heading">{time}</span>

      {/* Dynamic island */}
      <span className="absolute left-1/2 top-2.5 h-7 w-[104px] -translate-x-1/2 rounded-full bg-heading" />

      <span className="flex w-16 items-center justify-end gap-1 text-heading">
        <svg viewBox="0 0 18 12" className="h-3 w-4 fill-current">
          <rect x="0" y="8" width="3" height="4" rx="1" />
          <rect x="4.5" y="6" width="3" height="6" rx="1" />
          <rect x="9" y="3.5" width="3" height="8.5" rx="1" />
          <rect x="13.5" y="1" width="3" height="11" rx="1" />
        </svg>
        <svg viewBox="0 0 16 12" className="h-3 w-4 fill-current">
          <path d="M8 10.8 6.2 9a2.6 2.6 0 0 1 3.6 0L8 10.8Z" />
          <path
            d="M3.6 6.3a6.6 6.6 0 0 1 8.8 0"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
          <path
            d="M1 3.6a10.3 10.3 0 0 1 14 0"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
          />
        </svg>
        <svg viewBox="0 0 26 12" className="h-3 w-6">
          <rect
            x="0.5"
            y="0.5"
            width="21"
            height="11"
            rx="3"
            fill="none"
            stroke="currentColor"
            strokeOpacity="0.4"
          />
          <rect x="2" y="2" width="18" height="8" rx="1.8" fill="currentColor" />
          <path d="M23.5 4.2v3.6a2 2 0 0 0 0-3.6Z" fill="currentColor" fillOpacity="0.4" />
        </svg>
      </span>
    </div>
  );
}
