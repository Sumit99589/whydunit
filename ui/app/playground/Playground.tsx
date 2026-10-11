"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

const WORLDS = [
  { id: "3inc", title: "Three things went wrong at once", body: "A Safari-only signup bug ships, a teammate cuts the main ad budget, and Brazilian banks start declining cards." },
  { id: "deploy_only", title: "A deploy breaks signup on Safari", body: "One refactor, every iPhone affected." },
  { id: "ads_only", title: "An ad budget is cut", body: "Paid traffic runs out around midday, every day." },
  { id: "payments_only", title: "Card declines in Brazil", body: "Issuer-side declines jump for one country." },
  { id: "holiday_red_herring", title: "A holiday, and a harmless deploy the same morning", body: "Can it avoid blaming the deploy?" },
  { id: "outage", title: "A payments provider outage", body: "Six hours of API errors, on a status page." },
  { id: "competitor", title: "A competitor launches a free tier", body: "Signup intent drops after the news." },
  { id: "tracking", title: "The tracking breaks, not the business", body: "Signups vanish from the dashboard; revenue is fine.", metric: "signups" },
  { id: "noise", title: "Nothing is wrong", body: "Just an ordinary bad day." },
  { id: "seasonality", title: "A normal weekend dip", body: "Compared with the weekdays before it." },
];

export function Playground() {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  async function open(world: string, metric = "paid_subs") {
    setBusy(world);
    setError(null);
    try {
      const r = await fetch("/engine/cases", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ world: `fixture:${world}`, metric }) });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || "The engine refused the case");
      router.push(`/cases/${d.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }
  return (
    <>
      {error && <p className="mb-4 rounded-md border border-fail/40 p-3 text-sm text-fail">{error}</p>}
      <ul className="grid gap-3 sm:grid-cols-2">
        {WORLDS.map((w) => (
          <li key={w.id}>
            <button
              onClick={() => open(w.id, w.metric)}
              disabled={busy !== null}
              className="flex h-full w-full flex-col rounded-lg border border-line bg-surface p-4 text-left hover:border-ink-3 disabled:opacity-60"
            >
              <span className="font-semibold">{w.title}</span>
              <span className="mt-1 text-[13.5px] text-ink-2">{w.body}</span>
              <span className="mt-3 text-[12.5px] font-semibold text-ink">{busy === w.id ? "Opening the case…" : "Investigate this world"}</span>
            </button>
          </li>
        ))}
      </ul>
    </>
  );
}
