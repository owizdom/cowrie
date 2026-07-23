"use client";
/** Developers — API keys (FR 4.1). */
import { useState } from "react";
import { Card, CopyButton, Skeleton, cx } from "@/components/ui";
import { usePortal } from "../portal-context";

export default function KeysPage() {
  const { apiKey } = usePortal();
  const [shown, setShown] = useState(false);

  return (
    <div className="p-6 lg:p-8">
      <h1 className="text-xl font-bold tracking-tight text-heading">API keys</h1>
      <p className="mt-1 text-[13px] text-muted">Keys are shown once and stored hashed.</p>

      <Card className="mt-8 divide-y divide-line">
        <div className="flex items-center gap-3 px-5 py-4">
          <span className="h-2 w-2 shrink-0 rounded-full bg-success" />
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-heading">Sandbox secret</p>
            <p className="truncate font-mono text-[12px] text-muted">
              {shown ? apiKey : `${apiKey.slice(0, 14)}${"•".repeat(14)}`}
            </p>
          </div>
          <button type="button" onClick={() => setShown((v) => !v)} className="shrink-0 text-[12px] font-semibold text-violet-600">
            {shown ? "Hide" : "Reveal"}
          </button>
          <CopyButton value={apiKey} label="API key" />
        </div>
      </Card>

      <p className="mt-4 text-[12px] text-subtle">Scopes: payments:read · payments:write</p>
    </div>
  );
}
