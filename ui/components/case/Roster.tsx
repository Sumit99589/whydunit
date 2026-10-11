"use client";

import { motion, useReducedMotion } from "motion/react";
import { type CaseState, ROSTER } from "@/lib/case";

const DOT: Record<string, string> = { waiting: "var(--line)", working: "var(--marker)", done: "var(--pass)", error: "var(--fail)" };

export function Roster({ s, focus, onFocus }: { s: CaseState; focus: string | null; onFocus: (n: string | null) => void }) {
  const reduce = useReducedMotion();
  return (
    <div className="grid grid-cols-1 gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-2 lg:grid-cols-7">
      {ROSTER.map((r) => {
        const d = s.detectives[r.name];
        const on = focus === r.name;
        return (
          <button
            key={r.name}
            onClick={() => onFocus(on ? null : r.name)}
            aria-pressed={on}
            className={`flex min-h-[132px] flex-col gap-2 bg-surface p-3 text-left transition-colors hover:bg-surface-2 ${on ? "bg-surface-2" : ""}`}
          >
            <div className="flex items-center gap-2">
              <span className="relative flex h-2.5 w-2.5">
                {d.status === "working" && !reduce && (
                  <motion.span className="absolute inset-0 rounded-full" style={{ background: DOT.working }} animate={{ scale: [1, 2.2], opacity: [0.6, 0] }} transition={{ duration: 1.2, repeat: Infinity }} />
                )}
                <span className="relative h-2.5 w-2.5 rounded-full" style={{ background: DOT[d.status] }} />
              </span>
              <span className="font-semibold">{r.title}</span>
              {d.seconds != null && <span className="ml-auto text-[11px] text-ink-3 tabular-nums">{d.seconds.toFixed(1)}s</span>}
            </div>
            <p className="line-clamp-3 text-[12.5px] leading-snug text-ink-2">{d.status === "waiting" ? r.blurb : d.current}</p>
            <div className="mt-auto flex flex-wrap gap-x-3 gap-y-1 text-[11.5px] text-ink-3">
              {d.findings > 0 && <span><b className="text-ink">{d.findings}</b> finding{d.findings > 1 ? "s" : ""}</span>}
              {d.suspicions > 0 && <span className="text-fail">{d.suspicions} rejected</span>}
              {d.cannot > 0 && <span>{d.cannot} not checked</span>}
              {d.mode === "llm" && <span>Nemotron</span>}
              {d.note && <span className="w-full text-ink-3" title={d.note}>{d.note.startsWith("model") ? "Model unavailable: used computed findings" : d.note.slice(0, 60)}</span>}
            </div>
          </button>
        );
      })}
    </div>
  );
}
