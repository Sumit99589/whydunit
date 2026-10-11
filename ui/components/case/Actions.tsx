"use client";

import type { CaseState } from "@/lib/case";

const TYPE_LABEL: Record<string, string> = {
  code_pr: "Code fix (pull request)",
  config: "Config change (needs approval)",
  recommendation: "Recommendation",
  none: "No action needed",
};

export function Actions({ s, children }: { s: CaseState; children?: React.ReactNode }) {
  const v = s.verdict;
  if (!v || !v.actions.length) return null;
  return (
    <section aria-labelledby="fix-h" className="space-y-3">
      <h2 id="fix-h" className="text-[15px] font-semibold">Fix and verify</h2>
      <ul className="space-y-2">
        {v.actions.map((a, i) => {
          const fix = Object.values(s.fixes).find((f) => f.title === a.title);
          return (
            <li key={i} className="rounded-lg border border-line bg-surface p-3 text-[13.5px]">
              <div className="text-[11.5px] text-ink-3">{TYPE_LABEL[a.type] ?? a.type}</div>
              <div className="font-semibold">{a.title}</div>
              {fix ? (
                <div className="mt-1 text-[12.5px] text-ink-2">
                  {fix.status.replaceAll("_", " ")}
                  {fix.pr_url && (<a className="ml-2 underline" href={fix.pr_url} target="_blank" rel="noreferrer">Open the pull request</a>)}
                  {fix.log.length > 0 && <span className="block text-ink-3">{fix.log[fix.log.length - 1]}</span>}
                </div>
              ) : null}
            </li>
          );
        })}
      </ul>
      {children}
    </section>
  );
}
