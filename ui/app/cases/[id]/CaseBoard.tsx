"use client";

import { use, useEffect, useMemo, useState } from "react";
import { Actions } from "@/components/case/Actions";
import { EvidenceBoard } from "@/components/case/EvidenceBoard";
import { CaseHeader } from "@/components/case/Header";
import { MetricChart, type Series } from "@/components/case/MetricChart";
import { Roster } from "@/components/case/Roster";
import { Thread } from "@/components/case/Thread";
import { HowWeKnow, VerdictPanel } from "@/components/case/Verdict";
import { CAUSE_COLORS } from "@/lib/case";
import { type Mode, useCase } from "@/lib/useCase";

export function CaseBoard({ params, replayParam }: { params: Promise<{ id: string }>; replayParam: Promise<string | null> }) {
  const { id } = use(params);
  const initialReplay = use(replayParam);
  const [mode, setMode] = useState<Mode>(initialReplay ? { replay: true, speed: Number(initialReplay) || 4, run: 0 } : { replay: false });
  const { state: s } = useCase(id, mode);
  const [series, setSeries] = useState<Series | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    let off = false;
    fetch(`/engine/cases/${id}/series`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => !off && d && setSeries(d))
      .catch(() => {});
    return () => {
      off = true;
    };
  }, [id, s.verdict?.id]);

  const colorFor = useMemo(() => {
    const causes = s.verdict?.causes ?? [];
    return (label: string) => {
      const i = causes.findIndex((c) => c.statement === label);
      return i >= 0 ? CAUSE_COLORS[i % CAUSE_COLORS.length] : null;
    };
  }, [s.verdict]);

  const replay = (
    <div className="flex items-center gap-1" role="group" aria-label="Replay">
      {mode.replay ? (
        <>
          <span>Replaying at</span>
          {[1, 4, 16].map((sp) => (
            <button key={sp} onClick={() => setMode({ replay: true, speed: sp, run: mode.run + 1 })} aria-pressed={mode.speed === sp} className={`rounded px-1.5 py-0.5 ${mode.speed === sp ? "bg-ink text-bg" : "hover:bg-surface-2"}`}>
              {sp}×
            </button>
          ))}
          <button onClick={() => setMode({ replay: false })} className="ml-1 rounded px-1.5 py-0.5 underline hover:bg-surface-2">Show final</button>
        </>
      ) : (
        <button onClick={() => setMode({ replay: true, speed: 4, run: 0 })} className="rounded-md border border-line px-2.5 py-1 text-ink-2 hover:border-ink-3 hover:text-ink">
          Replay investigation
        </button>
      )}
    </div>
  );

  return (
    <div className="mx-auto max-w-[1400px] space-y-8 px-4 py-6 sm:px-6">
      <CaseHeader s={s} series={series} replay={replay} />
      <div className="grid gap-8 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)]">
        <section aria-labelledby="chart-h" className="min-w-0">
          <h2 id="chart-h" className="mb-2 text-[15px] font-semibold">New paid subscriptions, every six hours</h2>
          {series ? <MetricChart s={series} colorFor={colorFor} highlight={hover} /> : <div className="h-[220px] animate-pulse rounded-lg bg-surface-2" />}
        </section>
        <VerdictPanel s={s} onHover={setHover} />
      </div>
      <section aria-labelledby="team-h">
        <h2 id="team-h" className="mb-2 text-[15px] font-semibold">The detectives</h2>
        <Roster s={s} focus={focus} onFocus={setFocus} />
      </section>
      <EvidenceBoard s={s} focusDetective={focus} />
      <div className="grid gap-8 lg:grid-cols-2">
        <Thread s={s} />
        <div className="space-y-8">
          <HowWeKnow s={s} />
          <Actions s={s} />
        </div>
      </div>
    </div>
  );
}
