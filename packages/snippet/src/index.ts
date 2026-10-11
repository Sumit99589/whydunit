// Whydunit snippet: funnel events + sampled rrweb session recordings, uploaded to the engine's ingest API.
//
//   <script src="/whydunit.js"></script>
//   <script>whydunit.init({ key: "wd_…", endpoint: "/api/wd" })</script>
//   whydunit.track("signup_started", { plan: "pro" })

import { attributionFrom, channelOf, parseUA, uid, type Attribution } from "./context";

type RecordFn = (opts: Record<string, unknown>) => (() => void) | undefined;

export interface InitOptions {
  key: string;
  /** Base URL that proxies to the engine; `${endpoint}/ingest/events`. Default "/api/wd". */
  endpoint?: string;
  /** Share of sessions recorded with rrweb, 0..1. Default 0.1. */
  replaySampleRate?: number;
  /** URL of the recorder script, loaded only for sampled sessions. Default: next to this script. */
  recorderUrl?: string;
  /** Marks all data from this browser as synthetic (simulator traffic). */
  synthetic?: boolean;
  /** Simulated country; only sent for synthetic traffic. */
  country?: string;
  autoPageview?: boolean;
  debug?: boolean;
}

interface SessionState {
  id: string;
  last: number;
  replay: boolean;
  chunk: number;
  synthetic: boolean;
  country?: string;
  attr: Attribution;
}

interface QueuedEvent {
  event_id: string;
  name: string;
  ts: string;
  session_id: string;
  anon_id: string;
  user_id?: string;
  props: Record<string, unknown>;
  context: Record<string, unknown>;
}

const SESSION_TIMEOUT_MS = 30 * 60 * 1000;
const FLUSH_MS = 2000;
const REPLAY_FLUSH_MS = 5000;
const MAX_BATCH = 20;

let opts: Required<Omit<InitOptions, "country">> & { country?: string };
let started = false;
let anonId = "";
let userId: string | undefined;
let queue: QueuedEvent[] = [];
let replayBuf: unknown[] = [];
let stopRecording: (() => void) | undefined;
let timer: ReturnType<typeof setInterval> | undefined;

function log(...args: unknown[]) {
  if (opts?.debug) console.log("[whydunit]", ...args);
}

function store(kind: "local" | "session"): Storage | undefined {
  try {
    return kind === "local" ? window.localStorage : window.sessionStorage;
  } catch {
    return undefined;
  }
}

function readSession(): SessionState | undefined {
  try {
    const raw = store("session")?.getItem("wd_sess");
    return raw ? (JSON.parse(raw) as SessionState) : undefined;
  } catch {
    return undefined;
  }
}

function writeSession(s: SessionState) {
  store("session")?.setItem("wd_sess", JSON.stringify(s));
}

function urlFlag(name: string): string | null {
  return new URLSearchParams(location.search).get(name);
}

function session(): SessionState {
  const now = Date.now();
  let s = readSession();
  if (!s || now - s.last > SESSION_TIMEOUT_MS) {
    const forced = urlFlag("wd_replay");
    const replay = forced === "1" ? true : forced === "0" ? false : Math.random() < opts.replaySampleRate;
    const country = urlFlag("wd_country") || opts.country;
    s = {
      id: uid("s"),
      last: now,
      replay,
      chunk: 0,
      synthetic: opts.synthetic || urlFlag("wd_synthetic") === "1",
      country: country ? country.toUpperCase().slice(0, 2) : undefined,
      attr: attributionFrom(location.search, document.referrer, location.host),
    };
  }
  s.last = now;
  writeSession(s);
  return s;
}

function context(s: SessionState): Record<string, unknown> {
  const ua = parseUA(navigator.userAgent);
  const ctx: Record<string, unknown> = {
    ...ua,
    viewport: `${window.innerWidth}x${window.innerHeight}`,
    path: location.pathname,
    ...s.attr,
    channel: channelOf(s.attr),
  };
  if (s.synthetic) {
    ctx.synthetic = true;
    if (s.country) ctx.country = s.country;
  }
  return ctx;
}

function url(path: string): string {
  return `${opts.endpoint.replace(/\/$/, "")}${path}?key=${encodeURIComponent(opts.key)}`;
}

async function post(path: string, body: unknown, beacon = false): Promise<void> {
  const json = JSON.stringify(body);
  if (beacon && navigator.sendBeacon && json.length < 60000) {
    navigator.sendBeacon(url(path), new Blob([json], { type: "application/json" }));
    return;
  }
  const headers: Record<string, string> = { "content-type": "application/json" };
  let payload: BodyInit = json;
  if (!beacon && json.length > 32000 && typeof CompressionStream !== "undefined") {
    payload = await new Response(new Blob([json]).stream().pipeThrough(new CompressionStream("gzip"))).blob();
    headers["content-encoding"] = "gzip";
  }
  try {
    await fetch(url(path), { method: "POST", headers, body: payload, keepalive: beacon });
  } catch (e) {
    log("upload failed", e);
  }
}

export function flush(beacon = false): void {
  if (queue.length) {
    const events = queue;
    queue = [];
    void post("/ingest/events", { events }, beacon);
  }
  flushReplay(beacon);
}

function flushReplay(beacon = false) {
  if (!replayBuf.length) return;
  const s = readSession();
  if (!s) return;
  const events = replayBuf;
  replayBuf = [];
  const chunk = s.chunk;
  s.chunk += 1;
  writeSession(s);
  void post("/ingest/replay", { session_id: s.id, chunk_index: chunk, events }, beacon);
}

export function track(name: string, props: Record<string, unknown> = {}): void {
  if (!started) return;
  const s = session();
  queue.push({
    event_id: uid("e"),
    name,
    ts: new Date().toISOString(),
    session_id: s.id,
    anon_id: anonId,
    user_id: userId,
    props,
    context: context(s),
  });
  log("track", name, props);
  if (queue.length >= MAX_BATCH) flush();
}

export function page(): void {
  track("page_view", { title: document.title.slice(0, 120) });
}

export function identify(id: string): void {
  userId = id;
  store("local")?.setItem("wd_user", id);
}

let loading = false;

function startReplay() {
  if (stopRecording || loading) return;
  const w = window as unknown as { __whydunitRecord?: RecordFn };
  if (!w.__whydunitRecord) {
    // Only sampled sessions pay for the recorder (~75 KB): inject it, then start.
    loading = true;
    const tag = document.createElement("script");
    tag.src = opts.recorderUrl;
    tag.async = true;
    tag.onload = () => {
      loading = false;
      startReplay();
    };
    tag.onerror = () => {
      loading = false;
      log("recorder failed to load");
    };
    document.head.appendChild(tag);
    return;
  }
  stopRecording = w.__whydunitRecord({
    emit(event: unknown) {
      replayBuf.push(event);
      if (replayBuf.length >= 300) flushReplay();
    },
    maskAllInputs: true,
    blockClass: "wd-block",
    sampling: { mousemove: 100, scroll: 150, input: "last" },
  });
  log("recording session");
}

function defaultRecorderUrl(): string {
  const me = document.currentScript as HTMLScriptElement | null;
  const src = me?.src || Array.from(document.scripts).map((x) => x.src).find((x) => /whydunit(\.min)?\.js/.test(x)) || "/whydunit.js";
  return src.replace(/whydunit(\.min)?\.js(\?.*)?$/, "whydunit-record.js");
}

function hookHistory() {
  const wrap = (fn: "pushState" | "replaceState") => {
    const orig = history[fn];
    history[fn] = function (this: History, ...args: Parameters<History["pushState"]>) {
      const before = location.pathname;
      const out = orig.apply(this, args);
      if (location.pathname !== before) page();
      return out;
    } as History["pushState"];
  };
  wrap("pushState");
  wrap("replaceState");
  window.addEventListener("popstate", () => page());
}

export function init(options: InitOptions): void {
  if (started || typeof window === "undefined") return;
  if (!options?.key) throw new Error("whydunit.init: key is required");
  opts = {
    endpoint: "/api/wd",
    replaySampleRate: 0.1,
    synthetic: false,
    autoPageview: true,
    debug: false,
    recorderUrl: defaultRecorderUrl(),
    ...options,
  };
  started = true;
  const ls = store("local");
  anonId = ls?.getItem("wd_anon") || uid("a");
  ls?.setItem("wd_anon", anonId);
  userId = ls?.getItem("wd_user") || undefined;

  const s = session();
  if (s.replay) startReplay();
  if (opts.autoPageview) {
    page();
    hookHistory();
  }
  timer = setInterval(() => {
    if (queue.length) flush();
  }, FLUSH_MS);
  setInterval(() => flushReplay(), REPLAY_FLUSH_MS);
  const onHide = () => flush(true);
  window.addEventListener("pagehide", onHide);
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "hidden") onHide();
  });
}

export function shutdown(): void {
  flush(true);
  stopRecording?.();
  stopRecording = undefined;
  if (timer) clearInterval(timer);
  started = false;
}

export function sessionInfo(): { sessionId?: string; anonId: string; recording: boolean } {
  return { sessionId: readSession()?.id, anonId, recording: Boolean(stopRecording) };
}
