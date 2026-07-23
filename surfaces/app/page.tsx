"use client";

/** Cowrie — landing. Front door to the six surfaces. */

import { useEffect, useState } from "react";
import Link from "next/link";
import { CowrieMark } from "@/components/brand";
import { GetApp } from "@/components/get-app";
import { Skeleton, cx } from "@/components/ui";
import { api } from "@/lib/api";

type Corridor = {
  feeSchedule: { allInPercent: string };
  benchmark: { subSaharanAfricaAverage: string };
  settlement: { requiredConfirmations: number; blockSeconds: number };
};

const SURFACES = [
  { href: "/pay", title: "CowriePay", who: "Individuals" },
  { href: "/developers", title: "Developers", who: "Banks & fintechs" },
  { href: "/admin", title: "Admin", who: "Compliance" },
  { href: "/regulator", title: "Regulator", who: "SEC · CMA · CBN" },
  { href: "/transparency", title: "Transparency", who: "Public" },
];

export default function LandingPage() {
  const [corridor, setCorridor] = useState<Corridor | null>(null);

  useEffect(() => {
    void (async () => {
      try { setCorridor(await api<Corridor>("/corridor")); } catch { setCorridor(null); }
    })();
  }, []);

  const settle = corridor ? corridor.settlement.requiredConfirmations * corridor.settlement.blockSeconds : null;

  return (
    <div className="min-h-screen bg-white">
      <header className="mx-auto flex max-w-4xl items-center justify-between px-6 py-6">
        <span className="flex items-center gap-2">
          <CowrieMark className="h-6 w-6 text-violet-600" />
          <span className="text-[15px] font-semibold tracking-tight text-heading">Cowrie</span>
        </span>
        <Link href="/pay" className="text-[13px] font-semibold text-violet-600 hover:text-violet-700">
          Open CowriePay →
        </Link>
      </header>

      <main id="main" className="mx-auto max-w-4xl px-6">
        <section className="py-20 sm:py-28">
          <p className="text-[12px] font-medium text-subtle">Nigeria → Kenya</p>
          <h1 className="mt-3 max-w-2xl text-[34px] font-bold leading-[1.15] tracking-tight text-heading sm:text-[44px]">
            Send naira. They receive shillings. Thirty seconds, under 1%.
          </h1>
          <p className="mt-5 max-w-lg text-[15px] leading-relaxed text-muted">
            Sending money within Africa costs {corridor?.benchmark.subSaharanAfricaAverage ?? "7.4"}% and takes
            days, because it detours through correspondent banks and dollars. Cowrie removes the detour.
          </p>

          <div className="mt-8 flex flex-wrap items-start gap-4">
            <GetApp />
            <Link href="/developers" className="inline-flex h-11 items-center rounded-field px-5 text-sm font-semibold text-muted hover:text-ink">
              Developer portal
            </Link>
          </div>

          <dl className="mt-16 flex flex-wrap gap-x-14 gap-y-8">
            <Figure label="All-in cost" value={corridor ? `${corridor.feeSchedule.allInPercent}%` : null} accent />
            <Figure label="Settlement" value={settle ? `${settle}s` : null} accent />
            <Figure label="Refund guarantee" value="10 min" />
            <Figure label="Regional average" value={corridor ? `${corridor.benchmark.subSaharanAfricaAverage}%` : null} />
          </dl>
        </section>

        <section className="border-t border-line py-14">
          <ul className="grid gap-x-8 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
            {SURFACES.map((s) => (
              <li key={s.href}>
                <Link href={s.href} className="group block">
                  <p className="text-[15px] font-semibold text-heading group-hover:text-violet-600">{s.title}</p>
                  <p className="mt-0.5 text-[13px] text-subtle">{s.who}</p>
                </Link>
              </li>
            ))}
          </ul>
        </section>

      </main>

    </div>
  );
}

function Figure({ label, value, accent }: { label: string; value: string | null; accent?: boolean }) {
  return (
    <div>
      <dt className="text-[12px] text-subtle">{label}</dt>
      {value === null ? <Skeleton className="mt-1.5 h-7 w-16" /> : (
        <dd className={cx("mt-1 text-[28px] font-bold tabular-nums tracking-tight", accent ? "text-violet-600" : "text-heading")}>{value}</dd>
      )}
    </div>
  );
}
