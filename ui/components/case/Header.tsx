"use client";

import { type CaseState, fmtTime } from "@/lib/case";
import type { Series } from "./MetricChart";

const STEPS = ["investigating", "verdict", "fixing", "verifying", "closed"] as const;
const STEP_LABEL: Record<string, string> = { investigating: "Investigating", verdict: "Verdict", fixing: "Fixing", verifying: "Verifying", closed: "Closed" };

function dropFrom(s: CaseState, series: Series | null): { pct: number; now: number; before: number } | null {
  if (s.attribution) {
    const a = s.attribution;
    return { pct: a.actual / a.baseline_expected - 1, now: a.actual, before: a.baseline_expected };
  }
  if (!series) return null;
  const sum = (r: { start: string; end: string }) =>
    series.daily.filter((d) => d.t >= r.start.slice(0, 19) && new Date(d.t) < new Date(r.end)).reduce((n, d) => n + d.paid, 0);
  const before = sum(series.baseline);
  const now = sum(series.window);
  return before ? { pct: now / before - 1, now, before } : null;
}

export function CaseHeader({ s, series, replay }: { s: CaseState; series: Series | null; replay: React.ReactNode }) {
  const drop = dropFrom(s, series);
  const idx = STEPS.indexOf(s.status as (typeof STEPS)[number]);
  return (
    <header className="grid gap-6 border-b border-line pb-6 lg:grid-cols-[minmax(0,1fr)_auto]">
      <div className="min-w-0">
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12.5px] text-ink-3">
          <span>{s.worldLabel || "Loading case"}</span>
          {s.autoOpened && <span className="rounded bg-marker px-1.5 py-px font-semibold text-marker-ink">Opened by the watcher</span>}
          {s.window && <span>{fmtTime(s.window.start)} to {fmtTime(s.window.end)}</span>}
        </p>
        <h1 className="mt-2 text-[28px] font-bold leading-[1.1] tracking-[-0.02em] sm:text-[38px]">{s.question || " "}</h1>
        <ol className="mt-4 flex flex-wrap items-center gap-1.5 text-[12.5px]" aria-label="Case status">
          {STEPS.map((st, i) => (
            <li key={st} className="flex items-center gap-1.5">
              <span
                className={`rounded-full border px-2.5 py-1 ${i < idx ? "border-line text-ink-2" : i === idx ? "border-ink bg-ink font-semibold text-bg" : "border-dashed border-line text-ink-3"}`}
                aria-current={i === idx ? "step" : undefined}
              >
                {STEP_LABEL[st]}
              </span>
              {i < STEPS.length - 1 && <span className="h-px w-3 bg-line" />}
            </li>
          ))}
        </ol>
      </div>
      <div className="flex flex-col justify-between gap-4 lg:items-end lg:text-right">
        {drop && (
          <div>
            <div className="text-[56px] font-extrabold leading-none tracking-[-0.04em] tabular-nums" style={{ color: drop.pct < 0 ? "var(--fail)" : "var(--pass)" }}>
              {drop.pct < 0 ? "−" : "+"}
              {Math.abs(drop.pct * 100).toFixed(0)}%
            </div>
            <p className="mt-1 text-[13px] text-ink-2 tabular-nums">
              {drop.now.toFixed(0)} paid subscriptions, against {drop.before.toFixed(0)} the same days last week
            </p>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-3 text-[12.5px] text-ink-3 lg:justify-end">
          <span className="tabular-nums">Model spend ${s.cost.toFixed(3)}</span>
          {replay}
        </div>
      </div>
    </header>
  );
}
