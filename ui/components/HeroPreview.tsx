"use client";

import { motion, useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";
import { Marker } from "./Marker";

const TEAM = ["Funnel", "Deploy", "Session", "Payments", "Ads", "Voice", "World"];
const CAUSES = [
  { label: "Safari signup bug in deploy 4233f4e", share: 0.71, color: "var(--cause-1)" },
  { label: "Ad budget cut from $450 to $150", share: 0.24, color: "var(--cause-2)" },
  { label: "Card declines in Brazil", share: 0.09, color: "var(--cause-3)" },
];

/** A 20-second loop of a case: the question, the team at work, evidence pinned, the verdict. */
export function HeroPreview() {
  const reduce = useReducedMotion();
  const [phase, setPhase] = useState(reduce ? 3 : 0);
  useEffect(() => {
    if (reduce) return;
    const steps = [0, 1, 2, 3];
    let i = 0;
    const t = setInterval(() => {
      i = (i + 1) % steps.length;
      setPhase(steps[i]);
    }, 5000);
    return () => clearInterval(t);
  }, [reduce]);

  return (
    <div className="rounded-xl border border-line bg-surface p-5 shadow-[0_24px_60px_-36px_rgba(22,32,44,0.45)]" aria-label="Preview of a solved case">
      <p className="text-[12px] text-ink-3">Opened by the watcher, Thursday</p>
      <p className="mt-1 text-[19px] font-bold leading-tight tracking-tight">Why did new paid subscriptions fall 40%?</p>
      <div className="mt-4 grid grid-cols-7 gap-1.5">
        {TEAM.map((t, i) => (
          <div key={t} className="flex flex-col items-center gap-1">
            <motion.span
              className="h-2.5 w-2.5 rounded-full"
              animate={{ background: phase === 0 ? "var(--line)" : phase === 1 ? (i % 3 === 0 ? "var(--pass)" : "var(--marker)") : "var(--pass)" }}
              transition={{ delay: reduce ? 0 : i * 0.12 }}
            />
            <span className="text-[10px] text-ink-3">{t}</span>
          </div>
        ))}
      </div>
      <div className="mt-4 flex min-h-[28px] flex-wrap gap-1">
        {Array.from({ length: phase >= 1 ? (phase >= 2 ? 11 : 5) : 0 }).map((_, i) => (
          <motion.span key={i} initial={reduce ? false : { y: -6, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: reduce ? 0 : i * 0.15 }}>
            <Marker n={i + 1} size={24} />
          </motion.span>
        ))}
      </div>
      <div className="mt-4 space-y-2">
        {CAUSES.map((c, i) => (
          <div key={c.label} className="grid grid-cols-[minmax(0,1fr)_2.8rem] items-center gap-2">
            <div>
              <div className="truncate text-[12.5px] text-ink-2">{c.label}</div>
              <div className="mt-1 h-2 rounded-full bg-surface-2">
                <motion.div
                  className="h-2 rounded-full"
                  style={{ background: c.color, transformOrigin: "left" }}
                  animate={{ scaleX: phase >= 3 ? c.share : 0, width: "100%" }}
                  transition={{ delay: reduce ? 0 : 0.2 + i * 0.35, duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
                />
              </div>
            </div>
            <span className="text-right text-[13px] font-semibold tabular-nums" style={{ color: c.color, opacity: phase >= 3 ? 1 : 0.25 }}>
              {Math.round(c.share * 100)}%
            </span>
          </div>
        ))}
      </div>
      <p className="mt-4 text-[12.5px] text-ink-3">
        {["Seven detectives are briefed.", "They pull evidence from seven systems at once.", "The lead cross-examines them.", "Each cause, its share of the drop, and the fix."][phase]}
      </p>
    </div>
  );
}
