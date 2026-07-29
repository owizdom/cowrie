"use client";

/**
 * "Get the app" — the install entry point.
 *
 * Resolves to the best install route the visitor's device actually supports:
 *
 *   Android APK   when NEXT_PUBLIC_APK_URL is set, a direct download of the
 *                 signed Trusted Web Activity package.
 *   Android web   otherwise the native install prompt, which produces the same
 *                 home-screen app without going through Play.
 *   iOS           Safari never exposes a prompt, so it says how to do it.
 *   Desktop       opens the app.
 *
 * There is no button here that pretends to install something it cannot.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowDown, ArrowRight } from "@/components/icons";
import { cx } from "@/components/ui";

type InstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

const APK_URL = process.env.NEXT_PUBLIC_APK_URL ?? "";

export function GetApp({ className }: { className?: string }) {
  const [deferred, setDeferred] = useState<InstallPromptEvent | null>(null);
  const [platform, setPlatform] = useState<"unknown" | "ios" | "installed">("unknown");
  const [hint, setHint] = useState("");
  const [inSafari, setInSafari] = useState(true);

  useEffect(() => {
    const standalone =
      window.matchMedia("(display-mode: standalone)").matches ||
      (window.navigator as { standalone?: boolean }).standalone === true;
    if (standalone) {
      setPlatform("installed");
      return;
    }

    const ua = window.navigator.userAgent;
    if (/iPhone|iPad|iPod/.test(ua)) setPlatform("ios");
    // Add to Home Screen is a Safari feature; the other iOS browsers do not
    // have it, so the instructions have to differ.
    setInSafari(!/CriOS|FxiOS|EdgiOS|OPiOS/.test(ua));

    const onPrompt = (event: Event) => {
      event.preventDefault();
      setDeferred(event as InstallPromptEvent);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  const base =
    "inline-flex h-11 items-center gap-2 rounded-field bg-violet-600 px-5 text-sm font-semibold text-white hover:bg-violet-700";

  // A real APK exists — hand it over.
  if (APK_URL) {
    return (
      <span className={className}>
        <a href={APK_URL} download className={base}>
          <ArrowDown className="h-4 w-4" />
          Download for Android
        </a>
      </span>
    );
  }

  // Android / desktop Chrome: the native install prompt.
  if (deferred) {
    return (
      <span className={className}>
        <button
          type="button"
          className={base}
          onClick={async () => {
            await deferred.prompt();
            const choice = await deferred.userChoice;
            if (choice.outcome === "accepted") setPlatform("installed");
          }}
        >
          <ArrowDown className="h-4 w-4" />
          Install CowriePay
        </button>
      </span>
    );
  }

  if (platform === "ios") {
    // iOS has no install prompt to call - Safari has never implemented
    // beforeinstallprompt - so the honest thing is to show the two taps rather
    // than a button that appears to do it.
    return (
      <span className={className}>
        <button
          type="button"
          className={base}
          aria-expanded={Boolean(hint)}
          onClick={() => setHint("share")}
        >
          <ArrowDown className="h-4 w-4" />
          Install CowriePay
        </button>
        {hint ? (
          <span className="mt-2 block max-w-xs text-[12px] leading-relaxed text-subtle">
            {inSafari ? (
              <>
                Tap <strong className="text-ink">Share</strong> at the bottom of Safari, then{" "}
                <strong className="text-ink">Add to Home Screen</strong>. iPhone has no one-tap
                install — this is the only route Apple provides.
              </>
            ) : (
              <>
                Open this page in <strong className="text-ink">Safari</strong> first — Add to Home
                Screen is a Safari feature, and other iPhone browsers cannot install a web app.
              </>
            )}
          </span>
        ) : null}
      </span>
    );
  }

  return (
    <span className={className}>
      <Link href="/pay" className={base}>
        {platform === "installed" ? "Open CowriePay" : "Try CowriePay"}
        <ArrowRight className="h-4 w-4" />
      </Link>
    </span>
  );
}
