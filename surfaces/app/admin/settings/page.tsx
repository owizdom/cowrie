"use client";
/** Admin — settings: the RBAC matrix from SRS 2.3, stated plainly. */
import { Card, CardHeader, Notice } from "@/components/ui";

const ROLES = [
  ["Support", "Read the feed and the queues. No decisions."],
  ["Reviewer", "Everything Support can do, plus KYC approve / reject / freeze."],
  ["Officer", "Plus dispute resolution, account freezes and regulator exports."],
  ["Engineer", "Plus treasury operations: mint, burn, attest, anchor."],
  ["Admin", "Plus role grants."],
];

export default function SettingsPage() {
  return (
    <div className="space-y-4 p-4 lg:p-6">
      <div><h1 className="text-xl font-bold tracking-tight text-heading">Settings</h1>
        <p className="mt-1 text-[13px] text-muted">Role-based access control, as specified in SRS section 2.3.</p></div>
      <Card>
        <CardHeader title="Roles" subtitle="Each role includes everything below it." />
        <ul className="mt-3 divide-y divide-line border-t border-line">
          {ROLES.map(([name, description]) => (
            <li key={name} className="px-5 py-3.5">
              <p className="text-[13px] font-semibold text-heading">{name}</p>
              <p className="mt-0.5 text-[12px] text-muted">{description}</p>
            </li>
          ))}
        </ul>
      </Card>
      <p className="text-[12px] text-subtle">Enforced by the API, not the UI.</p>
    </div>
  );
}
