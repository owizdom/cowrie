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
        <span className="mt-2 block text-[12px] text-subtle">
          Or <Link href="/pay" className="font-medium text-violet-600 hover:underline">open in browser</Link>
        </span>
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
        <span className="mt-2 block text-[12px] text-subtle">Installs to your home screen</span>
      </span>
    );
  }

  if (platform === "ios") {
    return (
      <span className={className}>
        <button type="button" className={base} onClick={() => setHint("share")}>
          <ArrowDown className="h-4 w-4" />
          Install CowriePay
        </button>
        <span className="mt-2 block text-[12px] text-subtle">
          {hint ? "Tap Share, then Add to Home Screen" : "Add to your home screen"}
        </span>
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
