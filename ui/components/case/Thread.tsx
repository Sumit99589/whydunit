"use client";

import { type CaseState, ROSTER } from "@/lib/case";

const VERDICT_STYLE: Record<string, { label: string; color: string }> = {
  supports: { label: "Supports", color: "var(--pass)" },
  contradicts: { label: "Contradicts", color: "var(--fail)" },
  neutral: { label: "Neutral", color: "var(--ink-3)" },
  cannot_determine: { label: "Cannot determine", color: "var(--ink-3)" },
};

export function Thread({ s }: { s: CaseState }) {
  const title = (n: string) => ROSTER.find((r) => r.name === n)?.title ?? n;
  return (
    <section aria-labelledby="thread-h">
      <h2 id="thread-h" className="mb-2 text-[15px] font-semibold">Interrogation</h2>
      {s.brief && <p className="mb-3 text-[13px] text-ink-2">{s.brief}</p>}
      {s.thread.length === 0 ? (
        <p className="rounded-lg border border-dashed border-line p-4 text-sm text-ink-3">The lead detective questions the team once all seven reports are in.</p>
      ) : (
        <ol className="space-y-3">
          {s.thread.map((t) => {
            const v = t.answer ? VERDICT_STYLE[t.answer.verdict] ?? VERDICT_STYLE.neutral : null;
            return (
              <li key={t.id} className="text-[13.5px] leading-snug">
                <p>
                  <span className="font-semibold">Lead to {title(t.to)}:</span> {t.text}
                </p>
                {t.answer ? (
                  <p className="mt-1 border-l-2 pl-3 text-ink-2" style={{ borderColor: v!.color }}>
                    <span className="font-semibold" style={{ color: v!.color }}>{v!.label}.</span> {t.answer.text}
                  </p>
                ) : (
                  <p className="mt-1 border-l-2 border-line pl-3 text-ink-3">Checking…</p>
                )}
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
