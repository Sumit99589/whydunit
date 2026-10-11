"use client";

import { useEffect, useState } from "react";

interface Step { connector: string; tier: number; available: boolean; reason: string }
interface Kind { kind: string; active: string | null; active_tier: number | null; active_tier_label: string | null; ladder: Step[] }

const TIER_NAMES: Record<number, string> = { 1: "Official API", 2: "Warehouse", 3: "CSV export", 4: "Screen reading", 5: "Public web", 6: "Ask a human" };

function TestButton({ kind }: { kind: string }) {
  const [res, setRes] = useState<{ ok: boolean; summary?: string; message?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  return (
    <div className="mt-1">
      <button
        onClick={async () => {
          setBusy(true);
          const r = await fetch("/engine/connect/test", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ kind }) });
          setRes(await r.json().catch(() => ({ ok: false, message: "No answer from the engine." })));
          setBusy(false);
        }}
        className="text-[12px] underline decoration-line underline-offset-2 hover:decoration-ink"
      >
        {busy ? "Testing…" : "Test connection"}
      </button>
      {res && <p className={`text-[12px] ${res.ok ? "text-ink-2" : "text-fail"}`}>{res.ok ? res.summary : res.message}</p>}
    </div>
  );
}

export function Ladder() {
  const [data, setData] = useState<{ kinds: Kind[]; runner: { backend: string; available: boolean }[] } | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    fetch("/engine/connect").then((r) => (r.ok ? r.json() : Promise.reject())).then(setData).catch(() => setError(true));
  }, []);
  if (error) return <p className="text-sm text-fail">The engine is not reachable, so the connector status cannot be shown.</p>;
  if (!data) return <p className="text-sm text-ink-3">Checking every connector…</p>;
  return (
    <div className="space-y-8">
      <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
        {data.kinds.map((k) => (
          <li key={k.kind} className="grid gap-2 px-4 py-3 md:grid-cols-[12rem_minmax(0,1fr)]">
            <div>
              <div className="font-semibold capitalize">{k.kind.replaceAll("_", " ")}</div>
              <div className={`text-[12.5px] ${k.active ? "text-pass" : "text-fail"}`}>
                {k.active ? `Using ${k.active.replaceAll("_", " ")} (${TIER_NAMES[k.active_tier!]})` : "No source: detectives will say they cannot determine this"}
              </div>
              <TestButton kind={k.kind} />
            </div>
            <ol className="flex flex-wrap gap-1.5 text-[12px]">
              {k.ladder.map((s) => (
                <li key={s.connector} className={`rounded border px-2 py-1 ${s.available ? "border-pass/40" : "border-dashed border-line text-ink-3"}`} title={s.reason}>
                  <span className="text-ink-3">Tier {s.tier}</span> {s.connector.replaceAll("_", " ")}
                  {!s.available && s.reason && <span className="block text-[11px]">{s.reason}</span>}
                </li>
              ))}
              <li className="rounded border border-dashed border-line px-2 py-1 text-ink-3"><span>Tier 6</span> ask a human for an upload</li>
            </ol>
          </li>
        ))}
      </ul>
      <section>
        <h2 className="font-semibold">Browser runner</h2>
        <ul className="mt-2 flex flex-wrap gap-2 text-[13px]">
          {data.runner.map((r) => (
            <li key={r.backend} className={`rounded border px-2 py-1 ${r.available ? "border-pass/40" : "border-dashed border-line text-ink-3"}`}>
              {r.backend.replaceAll("_", " ")}: {r.available ? "ready" : "not configured"}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
