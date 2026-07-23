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
      <main id="main" className="mx-auto max-w-3xl space-y-5 px-5 py-8">
        <div><h1 className="text-2xl font-bold tracking-tight text-heading">{guide?.title ?? "Integration guide"}</h1>
          <p className="mt-1 text-[13px] text-muted">{guide?.corridor} · v{guide?.version}</p></div>
        {(guide?.sections ?? []).map((s) => (
          <Card key={s.title} className="p-5">
            <h2 className="text-[15px] font-semibold text-heading">{s.title}</h2>
            <p className="mt-2 text-[13px] leading-relaxed text-muted">{s.body}</p>
          </Card>
        ))}
        {guide ? (
          <Card className="p-5">
            <h2 className="text-[15px] font-semibold text-heading">Endpoints</h2>
            <ul className="mt-3 space-y-2">
              {guide.endpoints.map((e) => (
                <li key={e.path} className="flex flex-wrap items-baseline gap-2 text-[12px]">
                  <span className="rounded bg-canvas px-1.5 py-0.5 font-mono font-bold text-violet-700">{e.method}</span>
                  <code className="font-mono text-ink">{e.path}</code>
                  <span className="text-muted">— {e.purpose}</span>
                </li>
              ))}
            </ul>
          </Card>
        ) : null}
      </main>
    </div>
  );
}
