"use client";

import { useState } from "react";

const KINDS = ["payments", "support_tickets", "reviews", "ad_performance", "ad_changes", "deploys", "funnel_events", "sessions", "world_news", "holidays", "dependency_status"];

interface Upload {
  id: string;
  kind: string;
  filename: string;
  columns: string[];
  mapping: Record<string, string | null>;
  mapped_by: string;
  preview: Record<string, unknown>[];
  row_count: number;
}

export function UploadPanel({ initialKind, caseId }: { initialKind?: string; caseId?: string }) {
  const [kind, setKind] = useState(initialKind && KINDS.includes(initialKind) ? initialKind : "payments");
  const [up, setUp] = useState<Upload | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [key, setKey] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setBusy(true);
    setMsg(null);
    const fd = new FormData();
    fd.append("kind", kind);
    fd.append("file", file);
    if (caseId) fd.append("case_id", caseId);
    const r = await fetch("/engine/uploads", { method: "POST", body: fd });
    const d = await r.json().catch(() => ({}));
    setBusy(false);
    if (!r.ok) return setMsg({ ok: false, text: d.detail || "The upload was rejected." });
    setUp(d);
    setMapping(d.mapping);
  }

  async function confirm() {
    if (!up) return;
    setBusy(true);
    const r = await fetch(`/engine/uploads/${up.id}/confirm`, { method: "POST", headers: { "content-type": "application/json", "x-admin-key": key }, body: JSON.stringify({ mapping }) });
    const d = await r.json().catch(() => ({}));
    setBusy(false);
    setMsg(r.ok ? { ok: true, text: `${up.filename} is now a source for ${up.kind.replaceAll("_", " ")} (CSV export tier).` } : { ok: false, text: d.detail || "Could not confirm." });
  }

  return (
    <section className="rounded-lg border border-line bg-surface p-4" aria-labelledby="upload-h">
      <h2 id="upload-h" className="font-semibold">Upload a CSV export</h2>
      <p className="mt-1 text-[13px] text-ink-2">For tools without an API. Whydunit maps the columns to what detectives expect; check the mapping before confirming.</p>
      <div className="mt-3 flex flex-wrap items-center gap-2 text-[13px]">
        <label htmlFor="kind">Evidence kind</label>
        <select id="kind" value={kind} onChange={(e) => { setKind(e.target.value); setUp(null); }} className="rounded-md border border-line bg-bg px-2 py-1.5">
          {KINDS.map((k) => <option key={k} value={k}>{k.replaceAll("_", " ")}</option>)}
        </select>
        <label className="cursor-pointer rounded-md bg-ink px-3 py-1.5 font-semibold text-bg">
          {busy ? "Reading…" : "Choose CSV file"}
          <input type="file" accept=".csv,text/csv" className="sr-only" onChange={send} />
        </label>
      </div>
      {up && (
        <div className="mt-4 space-y-3 text-[13px]">
          <p className="text-ink-2">{up.filename}: {up.row_count.toLocaleString()} rows. Columns mapped by {up.mapped_by}.</p>
          <table className="w-full max-w-xl text-left">
            <thead><tr className="text-ink-3"><th className="py-1 font-normal">Whydunit needs</th><th className="py-1 font-normal">From your column</th></tr></thead>
            <tbody>
              {Object.keys(mapping).map((t) => (
                <tr key={t} className="border-t border-line">
                  <td className="py-1.5">{t.replaceAll("_", " ")}</td>
                  <td className="py-1.5">
                    <select value={mapping[t] ?? ""} onChange={(e) => setMapping({ ...mapping, [t]: e.target.value || null })} className="w-full rounded border border-line bg-bg px-1.5 py-1">
                      <option value="">(not in this file)</option>
                      {up.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="overflow-x-auto">
            <table className="text-[12px]">
              <thead><tr>{Object.keys(up.preview[0] ?? {}).map((k) => <th key={k} className="px-2 py-1 text-left font-normal text-ink-3">{k}</th>)}</tr></thead>
              <tbody>
                {up.preview.slice(0, 5).map((r, i) => (
                  <tr key={i} className="border-t border-line">{Object.values(r).map((v, j) => <td key={j} className="whitespace-nowrap px-2 py-1">{String(v ?? "")}</td>)}</tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="sr-only" htmlFor="admin">Admin key</label>
            <input id="admin" type="password" placeholder="Admin key" value={key} onChange={(e) => setKey(e.target.value)} className="w-40 rounded-md border border-line bg-bg px-2 py-1.5" />
            <button onClick={confirm} disabled={busy} className="rounded-md bg-ink px-3 py-1.5 font-semibold text-bg disabled:opacity-60">Use this file as a source</button>
          </div>
        </div>
      )}
      {msg && <p className={`mt-3 text-[13px] ${msg.ok ? "text-pass" : "text-fail"}`}>{msg.text}</p>}
    </section>
  );
}
