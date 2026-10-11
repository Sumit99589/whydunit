// Case board state, rebuilt from the engine's append-only event log (live or replayed).

export type Tier = 1 | 2 | 3 | 4 | 5 | 6;

export interface Evidence {
  n: number; // pin order on the wall
  id: string;
  kind: string;
  connector: string;
  tier: Tier;
  tier_label: string;
  confidence: number;
  summary: string;
  detective: string | null;
  artifacts: { type: string; ref: string | null; caption: string; meta?: Record<string, unknown> }[];
  row_count: number;
  notes: string[];
}

export interface Finding {
  id: string;
  detective: string;
  claim: string;
  kind: "observed" | "inference";
  evidence_ids: string[];
  confidence: number;
  status: "accepted" | "suspicion" | "rejected";
  rejection_reason?: string | null;
}

export interface Hypothesis {
  id: string;
  statement: string;
  status: "open" | "supported" | "rejected" | "inconclusive";
  reason: string;
  proposed_by: string;
  effect: { factor: string; segment: Record<string, unknown>; start: string | null };
}

export interface Cause {
  hypothesis_id: string;
  statement: string;
  factor: string;
  share: number;
  share_ci: [number, number];
  share_of_explained: number;
  lost: number;
  confidence: number;
  proposed_by: string;
  evidence: string[];
  start: string | null;
}

export interface Verdict {
  id: string;
  kind: "causes" | "no_real_drop" | "measurement" | "unexplained";
  narrative: string;
  causes: Cause[];
  unexplained: { lost?: number; share_of_drop?: number; share_of_drop_ci?: [number, number] };
  how_we_know: { hypothesis: string; mechanism: string[]; timing: string[]; corroboration: string[] }[];
  rejected: { statement: string; reason: string }[];
  inconclusive: { statement: string; reason: string }[];
  not_checked: string[];
  actions: { type: string; title: string; hypothesis_id?: string; approval_required?: boolean; detail?: Record<string, unknown> }[];
}

export interface ThreadItem {
  id: string;
  to: string;
  text: string;
  hypothesis: string;
  round: number;
  answer?: { text: string; verdict: string };
}

export interface DetectiveState {
  name: string;
  title: string;
  status: "waiting" | "working" | "done" | "error";
  current: string;
  log: string[];
  findings: number;
  suspicions: number;
  cannot: number;
  seconds?: number;
  mode?: string;
  note?: string;
}

export interface Attribution {
  baseline_expected: number;
  actual: number;
  observed_drop: number;
  effects: { id: string; label: string; lost: number; lost_ci: [number, number]; share_of_drop: number }[];
  unexplained: { lost: number; share_of_drop: number };
}

export interface FixState {
  id: string;
  type: string;
  title: string;
  status: string;
  detail: Record<string, unknown>;
  pr_url?: string | null;
  preview_url?: string | null;
  log: string[];
}

export interface CaseState {
  id: string;
  question: string;
  metric: string;
  world: string;
  worldLabel: string;
  window?: { start: string; end: string };
  baseline?: { start: string; end: string };
  status: "investigating" | "verdict" | "fixing" | "verifying" | "closed" | "failed";
  autoOpened: boolean;
  detectives: Record<string, DetectiveState>;
  evidence: Record<string, Evidence>;
  evidenceOrder: string[];
  findings: Finding[];
  hypotheses: Record<string, Hypothesis>;
  thread: ThreadItem[];
  brief?: string;
  attribution?: Attribution;
  verdict?: Verdict;
  fixes: Record<string, FixState>;
  requests: { id: string; kind: string; reason: string; detective: string }[];
  cost: number;
  lastSeq: number;
  done: boolean;
  startedAt?: string;
}

export const ROSTER: { name: string; title: string; blurb: string }[] = [
  { name: "funnel", title: "Funnel", blurb: "Where in the funnel, which segment, since when" },
  { name: "deploy", title: "Deploy", blurb: "Which deployment broke a flow, on which browsers" },
  { name: "session", title: "Session", blurb: "What failing users actually saw" },
  { name: "payments", title: "Payments", blurb: "Declines, codes, banks or us" },
  { name: "ads", title: "Ads", blurb: "Budgets, caps and account changes" },
  { name: "voice", title: "Voice", blurb: "Tickets, reviews and public chatter" },
  { name: "world", title: "World", blurb: "News, holidays and outages" },
];

export function emptyCase(id: string): CaseState {
  return {
    id,
    question: "",
    metric: "paid_subs",
    world: "",
    worldLabel: "",
    status: "investigating",
    autoOpened: false,
    detectives: Object.fromEntries(
      ROSTER.map((d) => [d.name, { name: d.name, title: d.title, status: "waiting", current: d.blurb, log: [], findings: 0, suspicions: 0, cannot: 0 }]),
    ),
    evidence: {},
    evidenceOrder: [],
    findings: [],
    hypotheses: {},
    thread: [],
    fixes: {},
    requests: [],
    cost: 0,
    lastSeq: 0,
    done: false,
  };
}

export interface CaseEvent {
  seq: number;
  ts: string;
  type: string;
  actor: string | null;
  payload: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
}

const TOOL_LABEL: Record<string, string> = {
  assess_change: "Testing whether the drop is real",
  segment_drilldown: "Breaking the change down by segment",
  change_timing: "Finding when it started",
  run_flows: "Running signup on every deploy × 5 browsers",
  git_compare: "Reading the diff",
  read_screenshot: "Reading the failure screenshot",
  session_heuristics: "Watching recordings for rage and dead clicks",
  render_keyframes: "Rendering keyframes",
};

function upd(s: CaseState, name: string, patch: Partial<DetectiveState>): CaseState {
  const d = s.detectives[name] ?? { name, title: name, status: "waiting", current: "", log: [], findings: 0, suspicions: 0, cannot: 0 };
  return { ...s, detectives: { ...s.detectives, [name]: { ...d, ...patch } } };
}

export function reduce(s: CaseState, e: CaseEvent): CaseState {
  if (e.seq <= s.lastSeq) return s;
  s = { ...s, lastSeq: e.seq };
  const p = e.payload;
  const who = e.actor ?? "";
  const d = s.detectives[who];
  switch (e.type) {
    case "case_opened":
      return {
        ...s,
        question: p.case.question,
        metric: p.case.metric,
        world: p.case.world,
        worldLabel: p.world_label,
        autoOpened: p.case.auto_opened,
        window: { start: p.case.window_start, end: p.case.window_end },
        baseline: { start: p.case.baseline_start, end: p.case.baseline_end },
        startedAt: e.ts,
      };
    case "detective_started":
      return upd(s, who, { status: "working", current: "Starting", log: [] });
    case "tool_call": {
      const label = TOOL_LABEL[p.tool] ?? p.tool.replaceAll("_", " ");
      return upd(s, who, { current: label, log: [...(d?.log ?? []), label].slice(-4) });
    }
    case "evidence_pinned": {
      const ev = p.evidence;
      if (s.evidence[ev.id]) return s;
      const n = s.evidenceOrder.length + 1;
      return {
        ...s,
        evidence: { ...s.evidence, [ev.id]: { ...ev, n, detective: who } },
        evidenceOrder: [...s.evidenceOrder, ev.id],
      };
    }
    case "finding":
    case "finding_rejected": {
      const f = { ...p.finding, detective: p.finding.detective || who } as Finding;
      const found = s.findings.some((x) => x.id === f.id);
      const findings = found ? s.findings.map((x) => (x.id === f.id ? f : x)) : [...s.findings, f];
      const s2 = { ...s, findings };
      if (who === "lead" || !s2.detectives[who]) return s2;
      const dd = s2.detectives[who];
      return upd(s2, who, e.type === "finding" ? { findings: dd.findings + (found ? 0 : 1) } : { suspicions: dd.suspicions + 1 });
    }
    case "cannot_determine":
      return d ? upd(s, who, { cannot: d.cannot + 1, current: `Cannot check ${p.kind.replaceAll("_", " ")}` }) : s;
    case "detective_report":
      return upd(s, who, {
        status: "done",
        current: p.report.summary,
        seconds: p.seconds,
        mode: p.report.model_mode,
        note: (p.report.notes ?? [])[0],
        cannot: p.report.cannot_determine.length,
      });
    case "detective_error":
      return d ? upd(s, who, { status: "error", current: p.error }) : s;
    case "hypothesis":
    case "judgement":
      return { ...s, hypotheses: { ...s.hypotheses, [p.hypothesis.id]: p.hypothesis } };
    case "brief":
      return { ...s, brief: p.text };
    case "question":
      return {
        ...s,
        thread: [...s.thread, { id: p.question.id, to: p.question.to, text: p.question.text, hypothesis: p.question.about_hypothesis, round: p.question.round }],
      };
    case "answer":
      return { ...s, thread: s.thread.map((t) => (t.id === p.question_id ? { ...t, answer: { text: p.answer.text, verdict: p.answer.verdict } } : t)) };
    case "attribution":
      return { ...s, attribution: p.attribution };
    case "verdict":
      return { ...s, verdict: p.verdict, status: "verdict" };
    case "investigation_complete":
      return { ...s, cost: p.cost?.cost_usd ?? s.cost, done: true };
    case "fix_proposed":
    case "fix_updated": {
      const f = p.fix as FixState;
      const prev = s.fixes[f.id];
      return {
        ...s,
        status: s.status === "verdict" ? "fixing" : s.status,
        fixes: { ...s.fixes, [f.id]: { ...prev, ...f, log: [...(prev?.log ?? []), ...(p.note ? [p.note] : [])] } },
      };
    }
    case "evidence_requested":
      return s.requests.some((r) => r.kind === p.request.kind)
        ? s
        : { ...s, requests: [...s.requests, { ...p.request, detective: who }] };
    case "verifying":
      return { ...s, status: "verifying" };
    case "case_closed":
      return { ...s, status: "closed", done: true };
    case "case_reopened":
      return { ...s, status: "verifying" };
    case "case_failed":
      return { ...s, status: "failed", done: true };
    default:
      return s;
  }
}

export const CAUSE_COLORS = ["var(--cause-1)", "var(--cause-2)", "var(--cause-3)", "var(--cause-4)"];

export function pct(x: number | undefined | null, digits = 0): string {
  if (x == null || Number.isNaN(x)) return "–";
  return `${(x * 100).toFixed(digits)}%`;
}

export function fmtTime(iso: string | null | undefined, withDay = true): string {
  if (!iso) return "";
  const d = new Date(iso);
  const day = d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
  return withDay ? `${day}, ${time} UTC` : `${time} UTC`;
}
