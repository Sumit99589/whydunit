"use client";

import { useEffect, useRef, useState } from "react";
import { fmtTime } from "@/lib/case";

export interface Series {
  window: { start: string; end: string };
  baseline: { start: string; end: string };
  daily: { t: string; paid: number; visitors: number; signups: number }[];
  six_hourly: { t: string; paid: number; visitors: number }[];
  annotations: { t: string; label: string; kind: string; status: string }[];
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(720);
  useEffect(() => {
    if (!ref.current) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, e.contentRect.width)));
    ro.observe(ref.current);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

export function MetricChart({ s, colorFor, highlight }: { s: Series; colorFor: (label: string) => string | null; highlight?: string | null }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const H = 220;
  const pad = { l: 34, r: 12, t: 26, b: 26 };
  const pts = s.six_hourly;
  if (!pts.length) return <div ref={ref} className="h-[220px]" />;
  const t0 = new Date(pts[0].t).getTime();
  const t1 = new Date(pts[pts.length - 1].t).getTime() + 6 * 3600e3;
  const ymax = Math.max(...pts.map((p) => p.paid), 1) * 1.15;
  const X = (t: number) => pad.l + ((t - t0) / (t1 - t0)) * (width - pad.l - pad.r);
  const Y = (v: number) => pad.t + (1 - v / ymax) * (H - pad.t - pad.b);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${X(new Date(p.t).getTime() + 3 * 3600e3).toFixed(1)},${Y(p.paid).toFixed(1)}`).join(" ");
  const area = `${d} L${X(t1 - 3 * 3600e3)},${Y(0)} L${X(t0 + 3 * 3600e3)},${Y(0)} Z`;
  const band = (r: { start: string; end: string }) => [X(new Date(r.start).getTime()), X(new Date(r.end).getTime())];
  const [b0, b1] = band(s.baseline);
  const [w0, w1] = band(s.window);
  const days: number[] = [];
  for (let t = Math.ceil(t0 / 86400e3) * 86400e3; t < t1; t += 86400e3) days.push(t);
  const ticks = [0, Math.round(ymax / 2.3), Math.round(ymax / 1.15)];
  const marks = s.annotations.filter((m) => m.status !== "rejected");

  return (
    <div ref={ref} className="w-full">
      <svg width={width} height={H} role="img" aria-label="New paid subscriptions every six hours, with the baseline and the window shaded">
        <rect x={b0} y={pad.t - 14} width={Math.max(b1 - b0, 0)} height={H - pad.t - pad.b + 14} fill="var(--surface-2)" />
        <text x={b0 + 6} y={pad.t - 4} fontSize="11" fill="var(--ink-3)">Same days last week</text>
        <rect x={w0} y={pad.t - 14} width={Math.max(w1 - w0, 0)} height={H - pad.t - pad.b + 14} fill="var(--marker)" opacity="0.12" />
        <text x={w0 + 6} y={pad.t - 4} fontSize="11" fill="var(--ink-2)" fontWeight="600">Window</text>
        {ticks.map((v) => (
          <g key={v}>
            <line x1={pad.l} x2={width - pad.r} y1={Y(v)} y2={Y(v)} stroke="var(--line)" strokeDasharray={v ? "2 4" : undefined} />
            <text x={pad.l - 6} y={Y(v) + 4} fontSize="10.5" textAnchor="end" fill="var(--ink-3)">{v}</text>
          </g>
        ))}
        {days.map((t, i) =>
          width > 520 || i % 2 === 0 ? (
            <text key={t} x={X(t + 12 * 3600e3)} y={H - 8} fontSize="10.5" textAnchor="middle" fill="var(--ink-3)">
              {new Date(t).toLocaleDateString("en-GB", { weekday: "short", day: "numeric", timeZone: "UTC" })}
            </text>
          ) : null,
        )}
        <path d={area} fill="var(--ink)" opacity="0.06" />
        <path d={d} fill="none" stroke="var(--ink)" strokeWidth="1.8" strokeLinejoin="round" />
        {marks.map((m, i) => {
          const x = X(new Date(m.t).getTime());
          const c = colorFor(m.label) ?? "var(--ink-3)";
          const on = highlight ? m.label === highlight : true;
          return (
            <g key={i} opacity={on ? 1 : 0.25}>
              <line x1={x} x2={x} y1={pad.t} y2={H - pad.b} stroke={c} strokeWidth="1.5" strokeDasharray="3 3" />
              <circle cx={x} cy={pad.t + 4} r="4.5" fill={c} />
              <title>{`${m.label} — ${fmtTime(m.t)}`}</title>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
