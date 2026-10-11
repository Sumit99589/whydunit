// The evidence marker: a numbered tent like the ones placed at a scene. Used for pinned evidence and the logo.
export function Marker({ n, size = 26, dim = false }: { n: number | string; size?: number; dim?: boolean }) {
  return (
    <svg width={size} height={size} viewBox="0 0 26 26" aria-hidden className="shrink-0">
      <path d="M3 22 L13 3 L23 22 Z" fill={dim ? "var(--surface-2)" : "var(--marker)"} stroke="var(--marker-ink)" strokeOpacity={dim ? 0.25 : 0.55} strokeWidth="1.2" strokeLinejoin="round" />
      <text x="13" y="19" textAnchor="middle" fontSize={String(n).length > 1 ? 7.5 : 9.5} fontWeight="800" fill="var(--marker-ink)">
        {n}
      </text>
    </svg>
  );
}
