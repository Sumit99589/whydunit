"use client";

import { useEffect, useReducer, useRef } from "react";
import { type CaseEvent, type CaseState, emptyCase, reduce } from "./case";

const TYPES = [
  "case_opened", "detective_started", "tool_call", "tool_result", "evidence_pinned", "finding", "finding_rejected",
  "cannot_determine", "detective_report", "detective_error", "lead_started", "hypothesis", "brief", "question", "answer",
  "judgement", "attribution", "verdict", "narrative_rejected", "investigation_complete", "fix_proposed", "fix_updated",
  "verifying", "verification", "case_closed", "case_reopened", "case_failed", "evidence_requested",
];

type Action = { kind: "event"; e: CaseEvent } | { kind: "reset"; id: string };

function reducer(s: CaseState, a: Action): CaseState {
  return a.kind === "reset" ? emptyCase(a.id) : reduce(s, a.e);
}

export type Mode = { replay: false } | { replay: true; speed: number; run: number };

/** Live: load the log so far, then follow the stream. Replay: re-emit the stored log at `speed`×. */
export function useCase(id: string, mode: Mode) {
  const [state, dispatch] = useReducer(reducer, id, emptyCase);
  const [connected, setConnected] = useReducerState(false);
  const esRef = useRef<EventSource | null>(null);
  const replayKey = mode.replay ? `${mode.speed}:${mode.run}` : "live";

  useEffect(() => {
    let closed = false;
    dispatch({ kind: "reset", id });
    const open = (url: string) => {
      const es = new EventSource(url);
      esRef.current = es;
      es.onopen = () => setConnected(true);
      es.onerror = () => setConnected(false);
      const onEvent = (msg: MessageEvent) => {
        try {
          dispatch({ kind: "event", e: JSON.parse(msg.data) as CaseEvent });
        } catch {}
      };
      for (const t of TYPES) es.addEventListener(t, onEvent as EventListener);
      es.addEventListener("end", () => es.close());
    };
    if (mode.replay) {
      open(`/engine/cases/${id}/stream?replay=1&speed=${mode.speed}`);
    } else {
      fetch(`/engine/cases/${id}/events`)
        .then((r) => (r.ok ? r.json() : []))
        .then((events: CaseEvent[]) => {
          if (closed) return;
          let last = 0;
          for (const e of events) {
            dispatch({ kind: "event", e });
            last = e.seq;
          }
          const done = events.some((e) => e.type === "case_closed" || e.type === "case_failed");
          if (!done) open(`/engine/cases/${id}/stream?after=${last}`);
        })
        .catch(() => open(`/engine/cases/${id}/stream`));
    }
    return () => {
      closed = true;
      esRef.current?.close();
      esRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, replayKey]);

  return { state, connected };
}

function useReducerState<T>(initial: T): [T, (v: T) => void] {
  const [v, set] = useReducer((_: T, n: T) => n, initial);
  return [v, set];
}
