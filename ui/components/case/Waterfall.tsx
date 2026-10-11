"use client";

import { motion, useReducedMotion } from "motion/react";
import { type Attribution, CAUSE_COLORS, type Cause, pct } from "@/lib/case";

interface Row {
  label: string;
  from: number;
  to: number;
  color: string;
  value: string;
  whisker?: [number, number];
  kind: "total" | "cause" | "rest";
  share?: string;
}

/** Last week → minus each cause (with its CI whisker) → minus what's unexplained → this week. */
export function Waterfall({ a, causes, onHover }: { a: Attribution; causes: Cause[]; onHover?: (id: string | null) => void }) {
  const reduce = useReducedMotion();
  const B = a.baseline_expected;
  const A = a.actual;
  const drop = B - A;
  const rows: Row[] = [{ label: "Same days last week", from: 0, to: B, color: "var(--ink-3)", value: B.toFixed(0), kind: "total" }];
  let level = B;
  causes.forEach((c, i) => {
    const lost = Math.min(c.share, 1) * drop;
    const lo = Math.max(c.share_ci[0], 0) * drop;
    const hi = Math.min(c.share_ci[1], 1) * drop;
    rows.push({
      label: c.statement,
      from: level - lost,
      to: level,
      color: CAUSE_COLORS[i % CAUSE_COLORS.length],
      value: `−${lost.toFixed(0)}`,
      share: pct(c.share),
      whisker: [level - hi, level - lo],
      kind: "cause",
    });
    level -= lost;
  });
  const rest = level - A;
  if (Math.abs(rest) >= 0.5) {
    rows.push({
      label: rest > 0 ? "Unexplained (noise)" : "Over-explained (noise)",
      from: Math.min(level, A),
      to: Math.max(level, A),
      color: "var(--unexplained)",
      value: rest > 0 ? `−${rest.toFixed(0)}` : `+${(-rest).toFixed(0)}`,
      share: pct(Math.abs(rest) / drop),
      kind: "rest",
    });
  }
  rows.push({ label: "This week", from: 0, to: A, color: "var(--ink)", value: A.toFixed(0), kind: "total" });

  const max = B * 1.04;
  const x = (v: number) => `${(Math.max(v, 0) / max) * 100}%`;
  const w = (r: Row) => `${(Math.max(r.to - r.from, 0.3) / max) * 100}%`;

  return (
    <figure className="space-y-2" aria-label="Blame waterfall: how the drop splits between causes">
      {rows.map((r, i) => (
        <div
          key={i}
          className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 sm:grid-cols-[11rem_minmax(0,1fr)_3.5rem]"
          onMouseEnter={() => r.kind === "cause" && onHover?.(causes[i - 1]?.hypothesis_id ?? null)}
          onMouseLeave={() => onHover?.(null)}
        >
          <div className={`truncate text-[13px] leading-tight sm:whitespace-normal ${r.kind === "total" ? "font-semibold" : "text-ink-2"}`} title={r.label}>
            {r.label}
          </div>
          <div className="relative col-span-2 h-6 sm:col-span-1 sm:order-none">
            <div className="absolute inset-y-[11px] left-0 right-0 border-t border-dashed border-line" />
            <motion.div
              className="absolute inset-y-0 rounded-[3px]"
              style={{ left: x(r.from), width: w(r), background: r.color, transformOrigin: r.kind === "total" ? "left" : "right" }}
              initial={reduce ? false : { scaleX: 0, opacity: 0.4 }}
              animate={{ scaleX: 1, opacity: r.kind === "rest" ? 0.7 : 1 }}
              transition={{ delay: reduce ? 0 : 0.15 + i * 0.32, duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
            />
            {r.whisker && (
              <motion.div
                className="absolute top-1/2 h-[9px] -translate-y-1/2 border-x-2 border-ink/70"
                style={{ left: x(r.whisker[0]), width: `${((r.whisker[1] - r.whisker[0]) / max) * 100}%` }}
                initial={reduce ? false : { opacity: 0 }}
                animate={{ opacity: 1 }}
                transition={{ delay: reduce ? 0 : 0.5 + i * 0.32 }}
              >
                <div className="absolute inset-x-0 top-1/2 border-t-2 border-ink/70" />
              </motion.div>
            )}
          </div>
          <div className="row-start-1 text-right text-[13px] font-semibold tabular-nums sm:row-start-auto" style={r.kind === "cause" ? { color: r.color } : undefined}>
            {r.share ?? r.value}
          </div>
        </div>
      ))}
      <figcaption className="pt-1 text-[12px] text-ink-3">
        Paid subscriptions in the window. Whiskers show each cause&rsquo;s 90% confidence interval; shares are exact Shapley values over counterfactuals computed by code.
      </figcaption>
    </figure>
  );
}
