"use client";

/**
 * Service worker registration and the install prompt.
 *
 * SRS 2.5: CowriePay ships as a Progressive Web App. Two things make that real
 * rather than a manifest sitting unused:
 *
 *   1. the service worker has to be registered, which is what gives the app an
 *      offline shell and lets Android treat it as installable;
 *   2. `beforeinstallprompt` has to be captured, because Chrome only lets you
 *      call prompt() from the event it handed you earlier.
 *
 * iOS does not fire beforeinstallprompt at all — Safari installs through Share →
 * Add to Home Screen — so the button explains that instead of pretending to be
 * broken.
 */

import { useEffect, useState } from "react";
import { ArrowDown, Close } from "@/components/icons";
import { cx } from "@/components/ui";

type InstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

const DISMISSED = "cowrie.install.dismissed";

export function InstallPrompt() {
  const [deferred, setDeferred] = useState<InstallPromptEvent | null>(null);
  const [iosHint, setIosHint] = useState(false);
  const [hidden, setHidden] = useState(true);

  useEffect(() => {
    // Register the worker. Failure is non-fatal: the app works online without
    // it, so a registration error must not take the page down.
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("/sw.js", { scope: "/pay" }).catch(() => {});
    }

    if (window.localStorage.getItem(DISMISSED)) return;

    // Already installed — nothing to offer.
    const standalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      (window.navigator as { standalone?: boolean }).standalone === true;
    if (standalone) return;

    const onPrompt = (event: Event) => {
      event.preventDefault();
      setDeferred(event as InstallPromptEvent);
      setHidden(false);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);

    // iOS never fires it, so detect Safari on iOS and show the manual route.
    const ua = window.navigator.userAgent;
    if (/iPhone|iPad|iPod/.test(ua) && /Safari/.test(ua) && !/CriOS|FxiOS/.test(ua)) {
      setIosHint(true);
      setHidden(false);
    }

    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  if (hidden) return null;

  const dismiss = () => {
    window.localStorage.setItem(DISMISSED, "1");
    setHidden(true);
  };

  return (
    <div className="mx-5 mb-3 flex items-center gap-3 rounded-card border border-violet-100 bg-violet-50 px-3.5 py-3">
      <ArrowDown className="h-4 w-4 shrink-0 text-violet-600" />
      <p className="min-w-0 flex-1 text-[12px] text-ink">
        {iosHint ? (
          <>
            Install CowriePay — tap <strong>Share</strong> then <strong>Add to Home Screen</strong>
          </>
        ) : (
          "Install CowriePay on this device"
        )}
      </p>

      {!iosHint && deferred ? (
        <button
          type="button"
          onClick={async () => {
            await deferred.prompt();
            const choice = await deferred.userChoice;
            if (choice.outcome === "accepted") setHidden(true);
          }}
          className="shrink-0 rounded-pill bg-violet-600 px-3 py-1.5 text-[12px] font-semibold text-white hover:bg-violet-700"
        >
          Install
        </button>
      ) : null}

      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss"
        className="shrink-0 text-subtle hover:text-ink"
      >
        <Close className="h-4 w-4" />
      </button>
    </div>
  );
}
