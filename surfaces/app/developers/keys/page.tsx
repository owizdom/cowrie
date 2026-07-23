"use client";

/**
 * Developers — API keys.
 *
 * SRS 3.1: "...management of the API keys..."
 * FR 4.1:  "Let businesses generate API key pairs..."
 *
 * Generate, list and revoke. A new secret is shown once and never again — it is
 * stored hashed, so the portal genuinely cannot display it later.
 */

import { useCallback, useEffect, useState } from "react";
import { Key, Plus } from "@/components/icons";
import { Badge, Button, Card, CopyButton, ErrorText, Skeleton, cx } from "@/components/ui";
import { api } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import { usePortal } from "../portal-context";

type KeyRow = {
  id: string;
  label: string;
  prefix: string;
  scopes: string;
  environment: string;
  revoked: boolean;
  current: boolean;
  lastUsedAt: string | null;
  requestCount: number;
  createdAt: string;
};

export default function KeysPage() {
  const { apiKey } = usePortal();
  const [rows, setRows] = useState<KeyRow[] | null>(null);
  const [issued, setIssued] = useState<{ secretKey: string; publishableKey: string } | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setRows((await api<{ data: KeyRow[] }>("/v1/keys", { apiKey })).data);
    } catch {
      setRows([]);
    }
  }, [apiKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    setBusy("create");
    setError("");
    try {
      setIssued(
        await api<{ secretKey: string; publishableKey: string }>("/v1/keys", {
          method: "POST",
          apiKey,
        }),
      );
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create a key.");
    } finally {
      setBusy("");
    }
  };

  const revoke = async (id: string) => {
    setBusy(id);
    setError("");
    try {
      await api(`/v1/keys/${id}/revoke`, { method: "POST", apiKey });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not revoke that key.");
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="p-6 lg:p-8">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight text-heading">API keys</h1>
          <p className="mt-1 text-[13px] text-muted">Secrets are shown once and stored hashed.</p>
        </div>
        <Button loading={busy === "create"} onClick={create}>
          <Plus className="h-4 w-4" />
          Create key pair
        </Button>
      </div>

      {error ? (
        <div className="mt-4">
          <ErrorText>{error}</ErrorText>
        </div>
      ) : null}

      {issued ? (
        <Card className="mt-6 border-violet-200 bg-violet-50 p-5">
          <p className="text-[13px] font-semibold text-heading">New key pair</p>
          <p className="mt-0.5 text-[12px] text-muted">
            Copy the secret now — it cannot be shown again.
          </p>
          <div className="mt-3 space-y-2">
            <Issued label="Secret key" value={issued.secretKey} />
            <Issued label="Publishable key" value={issued.publishableKey} />
          </div>
          <button
            type="button"
            onClick={() => setIssued(null)}
            className="mt-3 text-[12px] font-semibold text-violet-700"
          >
            Done
          </button>
        </Card>
      ) : null}

      <ul className="mt-8 divide-y divide-line">
        {rows === null ? (
          <li className="py-4">
            <Skeleton className="h-10 w-full" />
          </li>
        ) : (
          rows.map((row) => (
            <li key={row.id} className="flex flex-wrap items-center gap-3 py-3.5">
              <Key
                className={cx("h-4 w-4 shrink-0", row.revoked ? "text-subtle" : "text-violet-600")}
              />
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-[13px] font-medium text-heading">
                  {row.label}
                  {row.current ? <Badge tone="progress">in use</Badge> : null}
                  {row.revoked ? <Badge tone="neutral">revoked</Badge> : null}
                </p>
                <p className="truncate font-mono text-[12px] text-muted">
                  {row.prefix}
                  {"•".repeat(12)}
                </p>
              </div>
              <span className="text-[11px] text-subtle">
                {row.lastUsedAt ? `used ${relativeTime(row.lastUsedAt)}` : "never used"}
              </span>
              {!row.revoked && !row.current ? (
                <button
                  type="button"
                  disabled={busy === row.id}
                  onClick={() => revoke(row.id)}
                  className="text-[12px] font-semibold text-danger disabled:opacity-50"
                >
                  {busy === row.id ? "Revoking…" : "Revoke"}
                </button>
              ) : null}
            </li>
          ))
        )}
      </ul>
    </div>
  );
}

function Issued({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-field border border-violet-200 bg-white p-3">
      <p className="text-[11px] text-subtle">{label}</p>
      <div className="mt-1 flex items-center gap-2">
        <code className="min-w-0 flex-1 truncate font-mono text-[12px] text-ink">{value}</code>
        <CopyButton value={value} label={label} />
      </div>
    </div>
  );
}
