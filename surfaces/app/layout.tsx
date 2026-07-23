import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Cowrie — a cross-border payment network for Africa",
    template: "%s · Cowrie",
  },
  description:
    "Cowrie settles payments between African currencies in seconds at under 1% in fees, " +
    "using cUSDC as the neutral bridge between local on-ramps and off-ramps.",
  applicationName: "Cowrie",
  manifest: "/manifest.webmanifest",
  appleWebApp: {
    // SRS 2.5: CowriePay ships as a Progressive Web App for this build.
    // These are what let it install to an iOS home screen and open without
    // Safari chrome, on iOS 14+ as SRS 2.4 requires.
    capable: true,
    title: "CowriePay",
    statusBarStyle: "default",
  },
  formatDetection: {
    // iOS otherwise turns every naira amount and reference into a phone link.
    telephone: false,
  },
  icons: {
    icon: [{ url: "/icon.svg", type: "image/svg+xml" }],
    apple: [{ url: "/apple-icon.png" }],
  },
  other: {
    "mobile-web-app-capable": "yes",
  },
};

export const viewport: Viewport = {
  themeColor: "#7C3AED",
  width: "device-width",
  initialScale: 1,
  // Deliberately not maximumScale: 1. Locking zoom is a common way to make a
  // payments app feel native and an equally common WCAG 1.4.4 failure — NFR 7
  // requires AA, so pinch-zoom stays.
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        {/* NFR 7: a keyboard user must be able to get past the navigation. */}
        <a
          href="#main"
          className="sr-only-focusable absolute left-4 top-4 z-50 rounded-field bg-violet-600 px-4 py-2 text-sm font-semibold text-white"
        >
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
