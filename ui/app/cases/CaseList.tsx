"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { fmtTime } from "@/lib/case";

interface Row {
  id: string;
  world: string;
  question: string;
  status: string;
  auto_opened: boolean;
  cost_usd: number;
  created_at: string;
}

export function CaseList() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    fetch("/engine/cases")
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setRows)
      .catch(() => setError(true));
  }, []);
  if (error) return <p className="text-sm text-fail">The engine is not reachable. Check that it is running and that WHYDUNIT_ENGINE_URL points at it.</p>;
  if (!rows) return <p className="text-sm text-ink-3">Loading cases…</p>;
  if (!rows.length)
    return (
      <p className="text-sm text-ink-2">
        No cases yet. <Link className="underline" href="/playground">Open one in the playground</Link>.
      </p>
    );
  return (
    <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
      {rows.map((r) => (
        <li key={r.id}>
          <Link href={`/cases/${r.id}`} className="grid gap-1 px-4 py-3 hover:bg-surface-2 sm:grid-cols-[minmax(0,1fr)_9rem_8rem] sm:items-center">
            <span className="min-w-0">
              <span className="block truncate font-semibold">{r.question}</span>
              <span className="text-[12.5px] text-ink-3">
                {r.world === "live" ? "Live Acme" : `Fixture world ${r.world.replace("fixture:", "")}`}, opened {fmtTime(r.created_at)}
              </span>
            </span>
            <span className="flex items-center gap-2 text-[13px]">
              <span className="capitalize">{r.status}</span>
              {r.auto_opened && <span className="rounded bg-marker px-1.5 text-[11px] font-semibold text-marker-ink">Auto-opened</span>}
            </span>
            <span className="text-[12.5px] text-ink-3 tabular-nums sm:text-right">${r.cost_usd.toFixed(3)} in model calls</span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
