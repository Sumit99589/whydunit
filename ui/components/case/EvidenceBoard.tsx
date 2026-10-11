"use client";

import { useState } from "react";
import { Marker } from "@/components/Marker";
import { type CaseState, type Evidence, ROSTER } from "@/lib/case";

const TIER_STYLE: Record<number, string> = {
  1: "border-pass/40 text-pass",
  2: "border-pass/30 text-pass",
  3: "border-ink-3/40 text-ink-2",
  4: "border-fail/40 text-fail",
  5: "border-ink-3/40 text-ink-2",
  6: "border-ink-3/40 text-ink-2",
};

const CONNECTOR: Record<string, string> = {
  whydunit_events: "Whydunit tracking", replays: "session recordings", vercel: "Vercel", github: "GitHub",
  stripe: "Stripe (test mode)", acme_payment_log: "Acme's payment log", mock_ads: "the simulated ad platform",
  acme_helpdesk: "Acme's helpdesk", acme_reviews: "app reviews", tavily: "Tavily", nager_holidays: "Nager.Date",
  statuspages: "status pages",
};

function sourceName(e: Evidence): string {
  if (e.connector === "whydunit-analysis") return "Computed by Whydunit";
  const kind = e.kind.replaceAll("_", " ");
  const from = e.connector.startsWith("fixture:") ? "the fixture world" : (CONNECTOR[e.connector] ?? e.connector);
  return `${kind[0].toUpperCase()}${kind.slice(1)} from ${from}`;
}

export function EvidenceBoard({ s, focusDetective }: { s: CaseState; focusDetective: string | null }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [show, setShow] = useState<"sources" | "all">("sources");
  const findings = s.findings.filter((f) => f.detective !== "lead" && (!focusDetective || f.detective === focusDetective));
  const sel = findings.find((f) => f.id === selected) ?? null;
  const lit = new Set(sel?.evidence_ids ?? []);
  const evidence = s.evidenceOrder
    .map((id) => s.evidence[id])
    .filter((e) => (show === "all" || !e.kind.startsWith("analysis:") || lit.has(e.id)) && (!focusDetective || e.detective === focusDetective || lit.has(e.id)));
  const title = (n: string) => ROSTER.find((r) => r.name === n)?.title ?? n;

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <section aria-labelledby="findings-h">
        <h2 id="findings-h" className="mb-2 text-[15px] font-semibold">Findings {focusDetective && <span className="font-normal text-ink-3">from {title(focusDetective)}</span>}</h2>
        <p className="mb-3 text-[12.5px] text-ink-3">Every finding cites evidence the detectives fetched or computed. Select one to light up its evidence.</p>
        {s.requests.length > 0 && (
          <ul className="mb-3 space-y-2">
            {s.requests.map((r) => (
              <li key={r.id} className="rounded-lg border border-dashed border-marker bg-surface p-3 text-[13px]">
                <p className="font-semibold">{title(r.detective)} detective requests evidence: {r.kind.replaceAll("_", " ")}</p>
                <p className="mt-0.5 text-ink-2">No connected source can supply it, so the investigation carries on without it.</p>
                <a href={`/connect?kind=${r.kind}&case=${s.id}`} className="mt-1.5 inline-block font-semibold underline">Upload a CSV export</a>
              </li>
            ))}
          </ul>
        )}
        <ol className="space-y-2">
          {findings.length === 0 && <li className="rounded-lg border border-dashed border-line p-4 text-sm text-ink-3">Findings appear here as each detective reports.</li>}
          {findings.map((f) => (
            <li key={f.id}>
              <button
                onClick={() => setSelected(selected === f.id ? null : f.id)}
                aria-pressed={selected === f.id}
                className={`w-full rounded-lg border p-3 text-left text-[13.5px] leading-snug transition-colors ${selected === f.id ? "border-marker bg-surface" : "border-line bg-surface hover:border-ink-3"} ${f.status !== "accepted" ? "opacity-70" : ""}`}
              >
                <div className="mb-1.5 flex items-center gap-2 text-[11.5px] text-ink-3">
                  <span className="font-semibold text-ink-2">{title(f.detective)}</span>
                  <span>{f.kind === "inference" ? "Inference" : "Observed"}</span>
                  <span className="ml-auto tabular-nums">confidence {(f.confidence * 100).toFixed(0)}%</span>
                </div>
                {f.claim}
                {f.status !== "accepted" && <div className="mt-1.5 text-[12px] text-fail">Rejected by the validator: {f.rejection_reason}</div>}
                <div className="mt-2 flex flex-wrap gap-1">
                  {f.evidence_ids.map((id) => s.evidence[id] && <Marker key={id} n={s.evidence[id].n} size={20} />)}
                </div>
              </button>
            </li>
          ))}
        </ol>
      </section>
      <section aria-labelledby="evidence-h">
        <div className="mb-2 flex items-center gap-3">
          <h2 id="evidence-h" className="text-[15px] font-semibold">Evidence wall</h2>
          <span className="text-[12.5px] text-ink-3 tabular-nums">{s.evidenceOrder.length} pinned</span>
          <div className="ml-auto flex rounded-md border border-line p-0.5 text-[12px]">
            {(["sources", "all"] as const).map((k) => (
              <button key={k} onClick={() => setShow(k)} aria-pressed={show === k} className={`rounded px-2 py-1 ${show === k ? "bg-surface-2 font-semibold" : "text-ink-3"}`}>
                {k === "sources" ? "Sources" : "Sources and analyses"}
              </button>
            ))}
          </div>
        </div>
        <ul className="grid gap-2 sm:grid-cols-2">
          {evidence.map((e) => (
            <li key={e.id} className={`rounded-lg border bg-surface p-3 transition-shadow ${lit.has(e.id) ? "border-marker shadow-[0_0_0_3px_color-mix(in_srgb,var(--marker)_35%,transparent)]" : "border-line"} ${sel && !lit.has(e.id) ? "opacity-45" : ""}`}>
              <div className="flex items-start gap-2.5">
                <Marker n={e.n} />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5 text-[11.5px] text-ink-3">
                    <span className="truncate">{sourceName(e)}</span>
                    <span className={`rounded border px-1.5 py-px ${TIER_STYLE[e.tier] ?? ""}`} title={`Tier ${e.tier} evidence, confidence weight ${e.confidence}`}>
                      {e.tier_label}
                    </span>
                  </div>
                  <p className="mt-1 text-[13px] leading-snug">{e.summary}</p>
                  {e.artifacts.filter((a) => a.type === "diff" && a.meta?.suspects).slice(0, 1).map((a, i) => (
                    <pre key={i} className="mt-2 max-h-28 overflow-auto rounded bg-surface-2 p-2 text-[11px] leading-snug">
                      {((a.meta?.suspects as { code: string; file: string; line: number }[]) ?? []).map((x) => `${x.file}:${x.line}\n+ ${x.code}`).join("\n")}
                    </pre>
                  ))}
                  {e.artifacts.filter((a) => a.type === "quote").slice(0, 1).map((a, i) => (
                    <blockquote key={i} className="mt-2 border-l-2 border-marker pl-2 text-[12.5px] italic text-ink-2">{a.ref}</blockquote>
                  ))}
                  {e.artifacts.filter((a) => a.type === "link").slice(0, 2).map((a, i) => (
                    <a key={i} href={a.ref ?? "#"} target="_blank" rel="noreferrer" className="mt-1 block truncate text-[12px] text-ink-2 underline decoration-line underline-offset-2">{a.caption || a.ref}</a>
                  ))}
                  {e.notes?.length > 0 && <p className="mt-1 text-[11.5px] text-ink-3">{e.notes[0]}</p>}
                </div>
              </div>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
