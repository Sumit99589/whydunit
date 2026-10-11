"use client";

import { useState } from "react";
import type { CaseState, FixState } from "@/lib/case";

const TYPE_LABEL: Record<string, string> = {
  code_pr: "Code fix, as a pull request",
  config: "Config change, needs approval",
  recommendation: "Recommendation",
  none: "No action needed",
};

const STATUS_LABEL: Record<string, string> = {
  proposed: "Proposed",
  proposed_only: "Proposal only",
  testing_preview: "Testing the preview deployment",
  awaiting_preview: "Waiting for the preview deployment",
  awaiting_verification: "Waiting for a browser runner",
  verified_on_preview: "Verified on the preview: every browser passes",
  failed_verification: "Still failing after two revisions",
  failed: "Could not be prepared",
  monitoring: "Applied: watching the metric recover",
  recovered: "Recovered",
};

const APPROVABLE = new Set(["proposed", "verified_on_preview", "awaiting_verification", "awaiting_preview"]);

function Approve({ caseId, fix }: { caseId: string; fix: FixState }) {
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const verb = fix.type === "code_pr" ? "Approve and merge" : fix.type === "config" ? "Approve and apply" : "Approve the mitigation";
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    const r = await fetch(`/engine/cases/${caseId}/fixes/${fix.id}/approve`, { method: "POST", headers: { "x-admin-key": key } });
    const d = await r.json().catch(() => ({}));
    setBusy(false);
    setMsg(r.ok ? "Approved. The board updates as the fix is applied." : d.detail || "The engine refused the approval.");
    if (r.ok) setOpen(false);
  }
  if (!open)
    return (
      <div className="mt-2">
        <button onClick={() => setOpen(true)} className="rounded-md bg-ink px-3 py-1.5 text-[12.5px] font-semibold text-bg hover:opacity-90">
          {verb}
        </button>
        {msg && <p className="mt-1 text-[12px] text-ink-2">{msg}</p>}
      </div>
    );
  return (
    <form onSubmit={submit} className="mt-2 flex flex-wrap items-center gap-2">
      <label className="sr-only" htmlFor={`key-${fix.id}`}>Admin key</label>
      <input
        id={`key-${fix.id}`}
        type="password"
        value={key}
        onChange={(e) => setKey(e.target.value)}
        placeholder="Admin key"
        className="w-40 rounded-md border border-line bg-bg px-2 py-1.5 text-[12.5px]"
      />
      <button disabled={busy} className="rounded-md bg-ink px-3 py-1.5 text-[12.5px] font-semibold text-bg disabled:opacity-60">
        {busy ? "Applying…" : verb}
      </button>
      <button type="button" onClick={() => setOpen(false)} className="text-[12.5px] text-ink-3 underline">Cancel</button>
      {msg && <p className="w-full text-[12px] text-fail">{msg}</p>}
    </form>
  );
}

export function Actions({ s }: { s: CaseState }) {
  const v = s.verdict;
  if (!v || !v.actions.length) return null;
  return (
    <section aria-labelledby="fix-h" className="space-y-3">
      <h2 id="fix-h" className="text-[15px] font-semibold">Fix and verify</h2>
      <ul className="space-y-2">
        {v.actions.map((a, i) => {
          const fix = Object.values(s.fixes).find((f) => f.title === a.title);
          const note = (fix?.detail?.note as string | undefined) ?? undefined;
          return (
            <li key={i} className="rounded-lg border border-line bg-surface p-3 text-[13.5px]">
              <div className="text-[11.5px] text-ink-3">{TYPE_LABEL[a.type] ?? a.type}</div>
              <div className="font-semibold">{a.title}</div>
              {fix && (
                <div className="mt-1 space-y-1 text-[12.5px] text-ink-2">
                  <p>
                    {STATUS_LABEL[fix.status] ?? fix.status.replaceAll("_", " ")}
                    {fix.pr_url && (
                      <a className="ml-2 underline" href={fix.pr_url} target="_blank" rel="noreferrer">Open the pull request</a>
                    )}
                    {fix.preview_url && (
                      <a className="ml-2 underline" href={fix.preview_url} target="_blank" rel="noreferrer">Preview</a>
                    )}
                  </p>
                  {note && <p className="text-ink-3">{note}</p>}
                  {fix.log.length > 0 && <p className="text-ink-3">{fix.log[fix.log.length - 1]}</p>}
                  {APPROVABLE.has(fix.status) && Boolean(fix.detail?.approval_required ?? true) && <Approve caseId={s.id} fix={fix} />}
                </div>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
