import type { Metadata } from "next";
import { SessionProvider } from "@/components/pay/session";
import { PhoneFrame } from "@/components/pay/phone-frame";

export const metadata: Metadata = {
  title: "CowriePay",
  description: "Send money from Nigeria to Kenya in seconds, for under 1% in fees.",
};

/**
 * CowriePay shell.
 *
 * On a phone the app fills the screen, which is what an installed PWA gets
 * (SRS 2.5). On a desktop browser it renders inside a device frame instead —
 * a 400px-wide consumer app stretched across a 1600px monitor would misrepresent
 * how it is actually used, and the frame is also what makes it legible in a
 * screen recording.
 */
export default function PayLayout({ children }: { children: React.ReactNode }) {
  return (
    <SessionProvider>
      <PhoneFrame>{children}</PhoneFrame>
    </SessionProvider>
  );
}
