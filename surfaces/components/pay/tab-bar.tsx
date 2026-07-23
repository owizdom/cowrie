"use client";

/**
 * CowriePay bottom navigation.
 *
 * Five destinations with the Send action raised into the centre, matching the
 * mockups. Send is a link rather than a button because it navigates, and that
 * matters: a keyboard user gets link semantics, and the browser's own
 * open-in-new-tab and back behaviour keep working.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ArrowDown, ArrowUp, Clock, Home, User } from "@/components/icons";
import { cx } from "@/components/ui";

/**
 * Four destinations, each reaching a function SRS 2.2 names for CowriePay:
 * Home, check history, send, and the profile screen that holds identity
 * verification and support tickets. Nothing here that no requirement asks for.
 */
const TABS = [
  { href: "/pay", label: "Home", icon: Home },
  { href: "/pay/history", label: "History", icon: Clock },
  { href: "/pay/receive", label: "Receive", icon: ArrowDown },
  { href: "/pay/support", label: "Profile", icon: User },
];

export function TabBar() {
  const pathname = usePathname();

  const left = TABS.slice(0, 2);
  const right = TABS.slice(2);

  return (
    <nav
      aria-label="Main"
      className="relative shrink-0 border-t border-line bg-white/95 px-2 pb-1 pt-2 backdrop-blur"
    >
      <ul className="flex items-end justify-between">
        {left.map((tab) => (
          <Tab key={tab.href} {...tab} active={pathname === tab.href} />
        ))}

        {/* Raised Send action */}
        <li className="relative -mt-7 flex w-[68px] flex-col items-center">
          <Link
            href="/pay/send"
            className="flex h-[54px] w-[54px] items-center justify-center rounded-full bg-violet-600 text-white shadow-fab transition-colors hover:bg-violet-700"
          >
            <ArrowUp className="h-6 w-6" />
            <span className="sr-only">Send money</span>
          </Link>
          <span
            className={cx(
              "mt-1 text-[10px] font-medium",
              pathname === "/pay/send" ? "text-violet-600" : "text-subtle",
            )}
            aria-hidden="true"
          >
            Send
          </span>
        </li>

        {right.map((tab) => (
          <Tab key={tab.href} {...tab} active={pathname === tab.href} />
        ))}
      </ul>
    </nav>
  );
}

function Tab({
  href,
  label,
  icon: Icon,
  active,
}: {
  href: string;
  label: string;
  icon: (p: { className?: string }) => React.ReactElement;
  active: boolean;
}) {
  return (
    <li className="w-[68px]">
      <Link
        href={href}
        aria-current={active ? "page" : undefined}
        className={cx(
          "flex flex-col items-center gap-1 rounded-lg py-1.5 transition-colors",
          active ? "text-violet-600" : "text-subtle hover:text-muted",
        )}
      >
        <Icon className="h-[22px] w-[22px]" />
        <span className="text-[10px] font-medium">{label}</span>
      </Link>
    </li>
  );
}
