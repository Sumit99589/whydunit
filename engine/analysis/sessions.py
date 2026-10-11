"""Session-recording heuristics computed from rrweb event streams (no model involved).

- rage click: 3+ clicks on the same element within 1 s
- dead click: a click followed by no DOM mutation and no navigation within 1 s
- form abandonment: the visitor typed into a form but never navigated away from the page afterwards
"""

from __future__ import annotations

from typing import Any

FULL_SNAPSHOT, INCREMENTAL, META = 2, 3, 4
SRC_MUTATION, SRC_MOUSE_INTERACTION, SRC_INPUT = 0, 2, 5
CLICK, TOUCH_END = 2, 9


def _index_snapshot(node: dict[str, Any], out: dict[int, dict[str, Any]]) -> str:
    """id -> {tag, text, attrs}; returns the node's text content."""
    text = ""
    if node.get("type") == 3:
        text = node.get("textContent", "")
    for ch in node.get("childNodes", []) or []:
        text += _index_snapshot(ch, out)
    if "id" in node and node.get("type") == 2:
        out[node["id"]] = {
            "tag": node.get("tagName"),
            "text": " ".join(text.split())[:80],
            "attrs": node.get("attributes", {}),
        }
    return text


def element_labels(events: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    labels: dict[int, dict[str, Any]] = {}
    for e in events:
        if e.get("type") == FULL_SNAPSHOT:
            _index_snapshot(e["data"]["node"], labels)
    return labels


def analyze(
    events: list[dict[str, Any]], *, rage_n: int = 3, rage_ms: int = 1000, dead_ms: int = 1000
) -> dict[str, Any]:
    events = sorted(events, key=lambda e: e.get("timestamp", 0))
    labels = element_labels(events)
    clicks = [
        e
        for e in events
        if e.get("type") == INCREMENTAL
        and e["data"].get("source") == SRC_MOUSE_INTERACTION
        and e["data"].get("type") == CLICK
    ]
    changes = [
        e["timestamp"]
        for e in events
        if (e.get("type") == INCREMENTAL and e["data"].get("source") == SRC_MUTATION)
        or e.get("type") in (META, FULL_SNAPSHOT)
    ]
    navs = [e for e in events if e.get("type") == META]
    inputs = [e for e in events if e.get("type") == INCREMENTAL and e["data"].get("source") == SRC_INPUT]

    dead = []
    for c in clicks:
        t = c["timestamp"]
        if not any(t < x <= t + dead_ms for x in changes):
            dead.append(c)
    # Group consecutive clicks on the same element with gaps of at most rage_ms; a group is a rage burst
    # when some rage_n consecutive clicks in it fall within rage_ms.
    groups: list[list[dict[str, Any]]] = []
    for c in clicks:
        g = groups[-1] if groups else None
        if (
            g
            and g[-1]["data"].get("id") == c["data"].get("id")
            and c["timestamp"] - g[-1]["timestamp"] <= rage_ms
        ):
            g.append(c)
        else:
            groups.append([c])
    bursts: list[dict[str, Any]] = []
    for g in groups:
        if len(g) >= rage_n and any(
            g[k + rage_n - 1]["timestamp"] - g[k]["timestamp"] <= rage_ms for k in range(len(g) - rage_n + 1)
        ):
            el = labels.get(g[0]["data"].get("id"), {})
            bursts.append(
                {
                    "element_id": g[0]["data"].get("id"),
                    "element": el.get("text") or el.get("tag"),
                    "clicks": len(g),
                    "start_ms": g[0]["timestamp"],
                    "end_ms": g[-1]["timestamp"],
                }
            )
    last_input = inputs[-1]["timestamp"] if inputs else None
    nav_after_input = last_input is not None and any(n["timestamp"] > last_input for n in navs)
    first = events[0]["timestamp"] if events else 0
    dead_els: dict[str, int] = {}
    for c in dead:
        el = labels.get(c["data"].get("id"), {})
        key = el.get("text") or el.get("tag") or str(c["data"].get("id"))
        dead_els[key] = dead_els.get(key, 0) + 1
    return {
        "duration_s": round((events[-1]["timestamp"] - first) / 1000, 1) if events else 0,
        "pages": [n["data"].get("href") for n in navs],
        "clicks": len(clicks),
        "dead_clicks": len(dead),
        "dead_click_elements": dead_els,
        "rage_bursts": bursts,
        "rage_clicks": sum(b["clicks"] for b in bursts),
        "typed_into_form": bool(inputs),
        "form_abandoned": bool(inputs) and not nav_after_input,
        "keyframe_times_ms": keyframe_times(events, clicks),
    }


def keyframe_times(
    events: list[dict[str, Any]], clicks: list[dict[str, Any]] | None = None, every_ms: int = 4000
) -> list[int]:
    """Moments worth rendering: each click, every few seconds, and the end."""
    if not events:
        return []
    start, end = events[0]["timestamp"], events[-1]["timestamp"]
    times = {start + 500, end}
    times.update(range(start + every_ms, end, every_ms))
    for c in clicks or []:
        times.add(c["timestamp"] + 150)
    return sorted(t for t in times if start <= t <= end)


def summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(results) or 1
    with_rage = sum(1 for r in results if r["rage_bursts"])
    with_dead = sum(1 for r in results if r["dead_clicks"])
    abandoned = sum(1 for r in results if r["form_abandoned"])
    elements: dict[str, int] = {}
    for r in results:
        for b in r["rage_bursts"]:
            elements[b["element"] or "?"] = elements.get(b["element"] or "?", 0) + 1
    return {
        "sessions": len(results),
        "with_rage_clicks": with_rage,
        "with_dead_clicks": with_dead,
        "form_abandoned": abandoned,
        "rage_share": with_rage / n,
        "dead_share": with_dead / n,
        "rage_elements": dict(sorted(elements.items(), key=lambda kv: -kv[1])),
    }
