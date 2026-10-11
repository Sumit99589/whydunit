"""Synthesise small but valid rrweb recordings of Acme's signup flow for fixture worlds.

Live-world recordings come from real browsers through the snippet; fixture worlds need recordings that
are deterministic and offline. These carry the same signals the Session detective looks for: inputs,
clicks, navigations, and (when signup is broken) repeated clicks on a button that changes nothing.
"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any

# rrweb event and source codes
DOM_LOADED, LOAD, FULL_SNAPSHOT, INCREMENTAL, META = 0, 1, 2, 3, 4
SRC_MUTATION, SRC_MOUSEMOVE, SRC_MOUSE_INTERACTION, SRC_SCROLL, SRC_INPUT = 0, 1, 2, 3, 5
MI_MOUSEUP, MI_MOUSEDOWN, MI_CLICK, MI_TOUCHSTART, MI_TOUCHEND = 0, 1, 2, 7, 9

BUTTON_ID = 23
FIELD_IDS = {"name": 20, "email": 21, "password": 22}


def _el(
    nid: int, tag: str, attrs: dict[str, str] | None = None, children: list | None = None
) -> dict[str, Any]:
    return {"type": 2, "tagName": tag, "attributes": attrs or {}, "childNodes": children or [], "id": nid}


def _text(nid: int, text: str) -> dict[str, Any]:
    return {"type": 3, "textContent": text, "id": nid}


def signup_snapshot() -> dict[str, Any]:
    style = (
        "body{font-family:system-ui;background:#fbf8f1;color:#17150f;margin:0}header{padding:20px;"
        "display:flex;justify-content:space-between}main{max-width:420px;margin:24px auto;padding:0 20px}"
        "label{display:block;margin:12px 0 4px;font-weight:600}input{width:100%;padding:12px;border:1px solid"
        " #ccc;border-radius:10px}button{width:100%;margin-top:16px;padding:14px;border-radius:10px;"
        "background:#17150f;color:#fbf8f1;border:0;font-weight:600}"
        ".cookie-banner{position:fixed;left:12px;right:12px;bottom:12px;background:#fff;padding:12px;"
        "border-radius:14px;border:1px solid #ddd}"
    )
    return {
        "node": {
            "type": 0,
            "id": 1,
            "childNodes": [
                {"type": 1, "name": "html", "publicId": "", "systemId": "", "id": 2},
                _el(
                    3,
                    "html",
                    {"lang": "en"},
                    [
                        _el(
                            4,
                            "head",
                            {},
                            [
                                _el(5, "title", {}, [_text(6, "Acme Notes")]),
                                _el(7, "style", {}, [_text(8, style)]),
                            ],
                        ),
                        _el(
                            9,
                            "body",
                            {},
                            [
                                _el(
                                    10,
                                    "header",
                                    {},
                                    [
                                        _el(11, "a", {"href": "/"}, [_text(12, "Acme Notes")]),
                                        _el(13, "a", {"href": "/pricing"}, [_text(14, "Pricing")]),
                                    ],
                                ),
                                _el(
                                    15,
                                    "main",
                                    {},
                                    [
                                        _el(16, "h1", {}, [_text(17, "Create your workspace")]),
                                        _el(
                                            18,
                                            "form",
                                            {"data-testid": "signup-form"},
                                            [
                                                _el(30, "label", {}, [_text(31, "Your name")]),
                                                _el(
                                                    FIELD_IDS["name"],
                                                    "input",
                                                    {"name": "name", "autocomplete": "name"},
                                                ),
                                                _el(32, "label", {}, [_text(33, "Work email")]),
                                                _el(
                                                    FIELD_IDS["email"],
                                                    "input",
                                                    {"name": "email", "type": "email"},
                                                ),
                                                _el(34, "label", {}, [_text(35, "Password")]),
                                                _el(
                                                    FIELD_IDS["password"],
                                                    "input",
                                                    {"name": "password", "type": "password"},
                                                ),
                                                _el(
                                                    BUTTON_ID,
                                                    "button",
                                                    {"type": "submit"},
                                                    [_text(24, "Create account")],
                                                ),
                                            ],
                                        ),
                                    ],
                                ),
                                _el(
                                    40,
                                    "div",
                                    {"class": "cookie-banner", "role": "dialog"},
                                    [_text(41, "We use a few cookies to keep you signed in.")],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        },
        "initialOffset": {"left": 0, "top": 0},
    }


def onboarding_snapshot() -> dict[str, Any]:
    return {
        "node": {
            "type": 0,
            "id": 1,
            "childNodes": [
                {"type": 1, "name": "html", "publicId": "", "systemId": "", "id": 2},
                _el(
                    3,
                    "html",
                    {"lang": "en"},
                    [
                        _el(4, "head"),
                        _el(
                            9,
                            "body",
                            {},
                            [
                                _el(
                                    15,
                                    "main",
                                    {},
                                    [
                                        _el(16, "h1", {}, [_text(17, "Welcome to Acme Notes")]),
                                        _el(
                                            50,
                                            "a",
                                            {"href": "/checkout", "data-testid": "go-checkout"},
                                            [_text(51, "Upgrade to Pro")],
                                        ),
                                    ],
                                )
                            ],
                        ),
                    ],
                ),
            ],
        },
        "initialOffset": {"left": 0, "top": 0},
    }


def recording(
    started: datetime, base_url: str, mobile: bool, outcome: str, rng: random.Random
) -> list[dict[str, Any]]:
    """outcome: 'signed_up' | 'blocked' | 'abandoned'."""
    t = int(started.timestamp() * 1000)
    w, h = (390, 844) if mobile else (1440, 900)
    ev: list[dict[str, Any]] = [
        {"type": META, "data": {"href": f"{base_url}/signup", "width": w, "height": h}, "timestamp": t},
        {"type": FULL_SNAPSHOT, "data": signup_snapshot(), "timestamp": t + 5},
    ]
    t += 400
    bx, by = (w // 2, 520) if mobile else (720, 470)

    def move(x: int, y: int) -> None:
        nonlocal t
        t += rng.randint(120, 600)
        if not mobile:
            ev.append(
                {
                    "type": INCREMENTAL,
                    "timestamp": t,
                    "data": {
                        "source": SRC_MOUSEMOVE,
                        "positions": [{"x": x, "y": y, "id": 9, "timeOffset": 0}],
                    },
                }
            )

    def tap(nid: int, x: int, y: int) -> None:
        nonlocal t
        kinds = (MI_TOUCHSTART, MI_TOUCHEND, MI_CLICK) if mobile else (MI_MOUSEDOWN, MI_MOUSEUP, MI_CLICK)
        for k in kinds:
            t += rng.randint(8, 60)
            ev.append(
                {
                    "type": INCREMENTAL,
                    "timestamp": t,
                    "data": {"source": SRC_MOUSE_INTERACTION, "type": k, "id": nid, "x": x, "y": y},
                }
            )

    for field, nid in FIELD_IDS.items():
        fy = {"name": 300, "email": 370, "password": 440}[field]
        move(bx, fy)
        tap(nid, bx, fy)
        length = rng.randint(8, 22)
        for i in range(1, length + 1, 3):
            t += rng.randint(150, 450)
            ev.append(
                {
                    "type": INCREMENTAL,
                    "timestamp": t,
                    "data": {"source": SRC_INPUT, "id": nid, "text": "*" * i, "isChecked": False},
                }
            )
        if outcome == "abandoned" and field == "email":
            t += rng.randint(3000, 9000)
            return ev
    move(bx, by)
    tap(BUTTON_ID, bx, by)
    if outcome == "signed_up":
        t += rng.randint(300, 900)
        ev.append(
            {
                "type": INCREMENTAL,
                "timestamp": t,
                "data": {
                    "source": SRC_MUTATION,
                    "texts": [{"id": 24, "value": "Creating your workspace…"}],
                    "attributes": [{"id": BUTTON_ID, "attributes": {"disabled": ""}}],
                    "removes": [],
                    "adds": [],
                },
            }
        )
        t += rng.randint(500, 1500)
        ev.append(
            {
                "type": META,
                "data": {"href": f"{base_url}/onboarding", "width": w, "height": h},
                "timestamp": t,
            }
        )
        ev.append({"type": FULL_SNAPSHOT, "data": onboarding_snapshot(), "timestamp": t + 5})
        return ev
    # Blocked: the button changes nothing. Pause, then a burst of repeated taps, then give up.
    t += rng.randint(1500, 4000)
    for _ in range(rng.randint(3, 6)):
        tap(BUTTON_ID, bx + rng.randint(-6, 6), by + rng.randint(-4, 4))
        t += rng.randint(120, 320)
    t += rng.randint(2000, 6000)
    if rng.random() < 0.5:
        tap(BUTTON_ID, bx, by)
    return ev
