"use client";
/** Regulator integration guide (SRS 2.6). Public — a regulator should be able to read how the portal works before being given access. */
import { useEffect, useState } from "react";
import Link from "next/link";
import { CowrieMark } from "@/components/brand";
import { Card } from "@/components/ui";
import { api } from "@/lib/api";

type Guide = { title: string; version: string; corridor: string; access: { method: string; session: string; regulators: string[] }; sections: Array<{ title: string; body: string }>; endpoints: Array<{ method: string; path: string; purpose: string }> };

export default function GuidePage() {
  const [guide, setGuide] = useState<Guide | null>(null);
  useEffect(() => { void (async () => { try { setGuide(await api<Guide>("/regulator/guide")); } catch { setGuide(null); } })(); }, []);

  return (
    <div className="min-h-screen bg-canvas">
      <header className="border-b border-line bg-white">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-5 py-4">
          <Link href="/regulator" className="flex items-center gap-2.5"><CowrieMark className="h-6 w-6 text-violet-600" />
            <span className="text-[15px] font-semibold text-heading">Regulator Portal</span></Link>
          <Link href="/regulator" className="text-[13px] font-semibold text-violet-600">Sign in →</Link>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-2xl px-6 pb-20">
        <h1 className="mt-6 text-[28px] font-bold tracking-tight text-heading">Regulator access</h1>
        <p className="mt-2 text-[14px] leading-relaxed text-muted">
          Read-only access to the NGN→KES transaction register, the cUSDC reserve position, and
          verification of the audit log.
        </p>

        <dl className="mt-10 space-y-6">
          <Item term="Access">
            An access code is issued per regulator. Sessions are read-only and expire after 12 hours.
          </Item>
          <Item term="Transactions">
            Every transfer in a chosen period, pseudonymised to a sender reference, country and KYC tier.
          </Item>
          <Item term="Reserves">
            Live cUSDC supply, the USD held against it, and the coverage ratio between them.
          </Item>
          <Item term="Audit log">
            Each entry carries the hash of the one before it. Verification reports the exact entry if
            the chain has been altered.
          </Item>
          <Item term="Screening">
            Every user is screened against OFAC, UN and EU lists at signup, on every transfer, and daily.
            Results are retained including passes.
          </Item>
          <Item term="Reports">
            Exports carry a SHA-256 content hash and a signature over it. Recomputing the hash from the
            CSV detects alteration.
          </Item>
        </dl>

        {guide ? (
          <>
            <h2 className="mt-14 border-t border-line pt-8 text-[15px] font-semibold text-heading">
              Endpoints
            </h2>
            <ul className="mt-4 space-y-2">
              {guide.endpoints.map((e) => (
                <li key={e.path} className="flex flex-wrap items-baseline gap-2 text-[12px]">
                  <span className="font-mono font-bold text-violet-700">{e.method}</span>
                  <code className="font-mono text-ink">{e.path}</code>
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </main>
    </div>
  );
}


function Item({ term, children }: { term: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[13px] font-semibold text-heading">{term}</dt>
      <dd className="mt-1 text-[13px] leading-relaxed text-muted">{children}</dd>
    </div>
  );
}
