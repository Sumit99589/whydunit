"use client";

import { CAUSE_COLORS, type CaseState, pct } from "@/lib/case";
import { Waterfall } from "./Waterfall";

export function VerdictPanel({ s, onHover }: { s: CaseState; onHover: (statement: string | null) => void }) {
  const v = s.verdict;
  if (!v) {
    const reporting = Object.values(s.detectives).filter((d) => d.status === "done").length;
    return (
      <section aria-labelledby="verdict-h" className="flex h-full flex-col justify-center rounded-lg border border-dashed border-line p-5">
        <h2 id="verdict-h" className="text-[15px] font-semibold">Verdict</h2>
        <p className="mt-1 text-sm text-ink-3">
          {s.thread.length ? "The lead detective is cross-examining the team." : `Waiting for reports: ${reporting} of 7 in.`}
        </p>
      </section>
    );
  }
  const statementOf = (id: string | null) => v.causes.find((c) => c.hypothesis_id === id)?.statement ?? null;
  return (
    <section aria-labelledby="verdict-h" className="space-y-4">
      <div className="flex items-baseline gap-2">
        <h2 id="verdict-h" className="text-[15px] font-semibold">Verdict</h2>
        <span className="text-[12.5px] text-ink-3">
          {v.kind === "causes" ? `${v.causes.length} cause${v.causes.length > 1 ? "s" : ""}, each with mechanism and timing confirmed` : v.kind === "no_real_drop" ? "No real drop" : v.kind === "measurement" ? "Measurement problem" : "Unexplained"}
        </span>
      </div>
      {v.kind === "causes" && s.attribution ? (
        <Waterfall a={s.attribution} causes={v.causes} onHover={(id) => onHover(statementOf(id))} />
      ) : null}
      <p className="text-[14.5px] leading-relaxed">{v.narrative}</p>
      {v.causes.length > 0 && (
        <ul className="space-y-1.5 text-[13px]">
          {v.causes.map((c, i) => (
            <li key={c.hypothesis_id} className="flex items-baseline gap-2">
              <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: CAUSE_COLORS[i % CAUSE_COLORS.length] }} />
              <span className="flex-1">{c.statement}</span>
              <span className="tabular-nums text-ink-3">confidence {pct(c.confidence)}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function HowWeKnow({ s }: { s: CaseState }) {
  const v = s.verdict;
  if (!v) return null;
  return (
    <section aria-labelledby="how-h" className="space-y-4">
      <h2 id="how-h" className="text-[15px] font-semibold">How we know</h2>
      {v.how_we_know.map((h, i) => (
        <details key={i} className="group rounded-lg border border-line bg-surface p-3" open={i === 0}>
          <summary className="cursor-pointer list-none text-[13.5px] font-semibold">
            <span className="mr-2 inline-block h-2.5 w-2.5 rounded-sm" style={{ background: CAUSE_COLORS[i % CAUSE_COLORS.length] }} />
            {h.hypothesis}
          </summary>
          <dl className="mt-2 space-y-2 text-[13px] leading-snug">
            {h.mechanism.length > 0 && (<div><dt className="text-ink-3">Mechanism</dt>{h.mechanism.map((m, k) => <dd key={k}>{m}</dd>)}</div>)}
            {h.timing.length > 0 && (<div><dt className="text-ink-3">Timing</dt>{h.timing.map((m, k) => <dd key={k}>{m}</dd>)}</div>)}
            {h.corroboration.length > 0 && (<div><dt className="text-ink-3">Corroboration</dt>{h.corroboration.map((m, k) => <dd key={k}>{m}</dd>)}</div>)}
          </dl>
        </details>
      ))}
      {(v.rejected.length > 0 || v.inconclusive.length > 0) && (
        <div className="text-[13px]">
          <h3 className="mb-1 font-semibold">Considered and set aside</h3>
          <ul className="space-y-1 text-ink-2">
            {[...v.rejected, ...v.inconclusive].map((r, i) => <li key={i}>{r.statement}: {r.reason}.</li>)}
          </ul>
        </div>
      )}
      <div className="text-[13px]">
        <h3 className="mb-1 font-semibold">Not checked</h3>
        {v.not_checked.length ? (
          <ul className="space-y-1 text-ink-2">{v.not_checked.map((n, i) => <li key={i}>{n}</li>)}</ul>
        ) : (
          <p className="text-ink-3">Every evidence source the team asked for was available.</p>
        )}
      </div>
    </section>
  );
}
