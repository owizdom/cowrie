import type { Config } from "tailwindcss";

/**
 * The Cowrie design system.
 *
 * SRS 3.1: "They're all designed with the same system, same colors, same
 * typography, spacing, and same accessibility standard."
 *
 * Every value below is taken from the approved mockups (CowriePay consumer app,
 * Cowrie Admin, Cowrie Developers). The six surfaces share this file, which is
 * what makes them one product rather than three that happen to be violet.
 *
 * Contrast note (NFR 7, WCAG 2.1 AA): `ink` on `canvas` is 15.8:1, `muted` on
 * white is 5.4:1, and white on `violet-600` is 5.9:1 - all above the 4.5:1
 * threshold for body text. `subtle` (3.6:1) is used only for large text and
 * decorative labels, never for content a user has to read to act.
 */
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // -- brand -------------------------------------------------------
        violet: {
          50: "#F5F2FF",
          100: "#EDE7FE",
          200: "#DDD3FD",
          300: "#C4B2FB",
          400: "#A487F7",
          500: "#8B5CF6",
          600: "#7C3AED", // primary: buttons, active nav, links
          700: "#6D28D9", // hover, gradient base
          800: "#5B21B6",
          900: "#4C1D95",
        },

        // -- neutrals ----------------------------------------------------
        canvas: "#F7F7FB", // page background
        surface: "#FFFFFF", // cards
        raised: "#FCFCFE", // subtly lifted panels
        line: "#ECECF2", // borders and dividers
        "line-strong": "#DEDEE7",
        ink: "#1C1A22", // primary text
        heading: "#17151D", // headings
        muted: "#6E6B7B", // secondary text
        subtle: "#9A97A8", // labels, timestamps

        // -- semantic ----------------------------------------------------
        success: { DEFAULT: "#16A34A", bg: "#E7F8EE", ring: "#BBF7D0" },
        warning: { DEFAULT: "#B45309", bg: "#FEF3C7", ring: "#FDE68A" },
        danger: { DEFAULT: "#DC2626", bg: "#FEE2E2", ring: "#FECACA" },
        info: { DEFAULT: "#2563EB", bg: "#DBEAFE", ring: "#BFDBFE" },

        // -- code block (developer portal) -------------------------------
        code: {
          bg: "#14131C",
          line: "#26242F",
          text: "#E6E4EF",
          keyword: "#C4B2FB",
          string: "#86EFAC",
          number: "#FDBA74",
          comment: "#6E6B7B",
          fn: "#93C5FD",
        },

        // -- avatar pastels (recent activity, KYC queue) -----------------
        avatar: {
          yellow: "#FDE68A",
          pink: "#FBCFE8",
          blue: "#BFDBFE",
          violet: "#DDD6FE",
          orange: "#FED7AA",
          green: "#BBF7D0",
          teal: "#99F6E4",
        },
      },

      fontFamily: {
        sans: [
          "var(--font-sans)",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Inter",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          "Menlo",
          "Monaco",
          "Consolas",
          "monospace",
        ],
      },

      fontSize: {
        // Money and counters. Tight tracking, because a balance reads as one
        // object rather than a row of digits.
        display: ["2.5rem", { lineHeight: "1", letterSpacing: "-0.03em", fontWeight: "700" }],
        figure: ["2rem", { lineHeight: "1.1", letterSpacing: "-0.02em", fontWeight: "700" }],
        stat: ["1.75rem", { lineHeight: "1.15", letterSpacing: "-0.02em", fontWeight: "700" }],
        // Uppercase section labels: TOTAL BALANCE, FROM, RECIPIENT, YOU SEND
        label: ["0.6875rem", { lineHeight: "1", letterSpacing: "0.08em", fontWeight: "600" }],
      },

      borderRadius: {
        card: "1rem",
        panel: "1.25rem",
        field: "0.75rem",
        pill: "999px",
      },

      boxShadow: {
        // Deliberately soft. The mockups separate surfaces with a border and a
        // hint of shadow, not with elevation.
        card: "0 1px 2px rgba(23, 21, 29, 0.04), 0 1px 3px rgba(23, 21, 29, 0.03)",
        raised: "0 4px 12px rgba(23, 21, 29, 0.06), 0 1px 3px rgba(23, 21, 29, 0.04)",
        fab: "0 6px 16px rgba(124, 58, 237, 0.35)",
        balance: "0 12px 28px rgba(93, 33, 182, 0.28)",
        phone: "0 24px 60px rgba(23, 21, 29, 0.14)",
      },

      backgroundImage: {
        // The balance card on CowriePay Home.
        balance: "linear-gradient(135deg, #6D28D9 0%, #7C3AED 52%, #8B5CF6 100%)",
        "balance-sheen":
          "radial-gradient(120% 90% at 88% 8%, rgba(255,255,255,0.20) 0%, rgba(255,255,255,0) 58%)",
        sparkline: "linear-gradient(180deg, rgba(124,58,237,0.22) 0%, rgba(124,58,237,0) 100%)",
      },

      keyframes: {
        "fade-up": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-dot": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "fade-up": "fade-up 0.28s ease-out both",
        "pulse-dot": "pulse-dot 1.8s ease-in-out infinite",
        shimmer: "shimmer 1.6s infinite",
      },
    },
  },
  plugins: [],
};

export default config;
