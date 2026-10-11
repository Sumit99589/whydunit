"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

interface Row {
  id: string;
  title: string;
  verdict_kind: string;
  expected_kind: string;
  top_cause_ok: boolean;
  share_abs_errors_pp: number[];
  false_accusations: string[];
  missed: string[];
  seconds: number;
  cost_usd: number;
  case_id: string;
  causes: { statement: string; share_of_explained: number; matched: string | null }[];
}
interface Summary {
  scenarios: number;
  top_cause_correct: number;
  share_mae_pp: number | null;
  false_accusations: number;
  false_accusation_rate: number;
  correct_abstention: string;
  missed_causes: number;
  mean_seconds: number;
  mean_cost_usd: number;
  model_mode: string;
}

export function Results() {
  const [data, setData] = useState<{ generated_at?: string; summary: Summary | null; scenarios: Row[] } | null>(null);
  useEffect(() => {
    fetch("/engine/evals").then((r) => r.json()).then(setData).catch(() => setData({ summary: null, scenarios: [] }));
  }, []);
  if (!data) return <p className="text-sm text-ink-3">Loading results…</p>;
  if (!data.summary) return <p className="text-sm text-ink-2">No results published yet. Run <code>uv run whydunit evals run</code>.</p>;
  const s = data.summary;
  const stats: [string, string][] = [
    ["Top cause right", `${s.top_cause_correct} of ${s.scenarios}`],
    ["False accusations", String(s.false_accusations)],
    ["Share error", s.share_mae_pp == null ? "–" : `${s.share_mae_pp} pp`],
    ["Correct abstentions", s.correct_abstention],
  ];
  return (
    <div className="space-y-6">
      <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-4">
        {stats.map(([k, v]) => (
          <div key={k} className="bg-surface p-4">
            <dt className="text-[12.5px] text-ink-3">{k}</dt>
            <dd className="mt-1 text-[26px] font-bold tabular-nums tracking-tight">{v}</dd>
          </div>
        ))}
      </dl>
      <div className="overflow-x-auto rounded-lg border border-line bg-surface">
        <table className="w-full min-w-[720px] text-left text-[13.5px]">
          <thead className="text-[12px] text-ink-3">
            <tr className="border-b border-line">
              <th className="px-3 py-2 font-normal">Scenario</th>
              <th className="px-3 py-2 font-normal">Verdict</th>
              <th className="px-3 py-2 font-normal">Causes named</th>
              <th className="px-3 py-2 font-normal">Right?</th>
              <th className="px-3 py-2 text-right font-normal">Time</th>
            </tr>
          </thead>
          <tbody>
            {data.scenarios.map((r) => (
              <tr key={r.id} className="border-b border-line align-top last:border-0">
                <td className="px-3 py-2.5">
                  <Link href={`/cases/${r.case_id}`} className="font-semibold hover:underline">{r.title}</Link>
                </td>
                <td className="px-3 py-2.5 capitalize">{r.verdict_kind.replaceAll("_", " ")}</td>
                <td className="px-3 py-2.5 text-ink-2">
                  {r.causes.length ? r.causes.map((c) => <div key={c.statement}>{c.statement} ({(c.share_of_explained * 100).toFixed(0)}%)</div>) : "None"}
                </td>
                <td className={`px-3 py-2.5 font-semibold ${r.top_cause_ok && !r.false_accusations.length ? "text-pass" : "text-fail"}`}>
                  {r.top_cause_ok && !r.false_accusations.length ? "Yes" : "No"}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums text-ink-3">{r.seconds.toFixed(1)} s</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-[12.5px] text-ink-3">
        Run in {s.model_mode} mode, averaging {s.mean_seconds} s and ${s.mean_cost_usd.toFixed(4)} per case
        {data.generated_at ? `, generated ${new Date(data.generated_at).toUTCString()}` : ""}. Share error compares each cause&rsquo;s share with the exact Shapley share computed from counterfactual worlds.
      </p>
    </div>
  );
}
