"""Token Factory client: role-based Nemotron selection, reasoning switch, retries, cache and cost meter.

Every model call in Whydunit goes through `LLM.chat`. Model IDs come only from config/models.yaml.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Protocol

from engine.runtime.cache import DiskCache, cache_key
from engine.settings import env, load_config

log = logging.getLogger("whydunit.llm")

Role = Literal["nano", "super", "ultra", "omni"]
ROLES: tuple[Role, ...] = ("nano", "super", "ultra", "omni")


class LLMUnavailable(RuntimeError):
    """No API key, or the model for a role is not served."""


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str = ""


@dataclass
class LLMResult:
    role: str
    model: str
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    cached: bool = False
    finish_reason: str | None = None

    def json(self) -> Any:
        """Parse `content` as JSON, tolerating markdown fences and leading prose."""
        return extract_json(self.content)


def extract_json(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        text = text.rsplit("```", 1)[0]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_ch, close_ch in (("{", "}"), ("[", "]")):
        start, end = text.find(open_ch), text.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"no JSON object in model output: {text[:200]!r}")


@dataclass
class CallRecord:
    role: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float
    latency_s: float
    cached: bool
    tag: str | None
    case_id: str | None


class CostMeter:
    """Accumulates usage for one scope (usually a case) and enforces its budget."""

    def __init__(
        self,
        case_id: str | None = None,
        max_cost_usd: float | None = None,
        sinks: list[Callable[[CallRecord], Awaitable[None] | None]] | None = None,
    ):
        self.case_id = case_id
        self.max_cost_usd = max_cost_usd
        self.calls: list[CallRecord] = []
        self.sinks = sinks or []

    @property
    def cost_usd(self) -> float:
        return sum(c.cost_usd for c in self.calls)

    @property
    def tokens(self) -> int:
        return sum(c.prompt_tokens + c.completion_tokens for c in self.calls)

    def check(self) -> None:
        if self.max_cost_usd is not None and self.cost_usd >= self.max_cost_usd:
            raise BudgetExceeded(f"case budget ${self.max_cost_usd:.2f} reached (${self.cost_usd:.4f} spent)")

    async def record(self, rec: CallRecord) -> None:
        self.calls.append(rec)
        for sink in self.sinks:
            out = sink(rec)
            if asyncio.iscoroutine(out):
                await out

    def summary(self) -> dict[str, Any]:
        by_role: dict[str, dict[str, float]] = {}
        for c in self.calls:
            r = by_role.setdefault(c.role, {"calls": 0, "tokens": 0, "cost_usd": 0.0})
            r["calls"] += 1
            r["tokens"] += c.prompt_tokens + c.completion_tokens
            r["cost_usd"] += c.cost_usd
        return {"cost_usd": round(self.cost_usd, 6), "tokens": self.tokens, "by_role": by_role}


class Backend(Protocol):
    async def complete(self, request: dict[str, Any]) -> dict[str, Any]: ...


class OpenAIBackend:
    """Token Factory is OpenAI-compatible; the key is sent as a Bearer token."""

    def __init__(self, base_url: str, api_key: str, timeout_s: float, max_retries: int):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout_s, max_retries=max_retries
        )

    async def complete(self, request: dict[str, Any]) -> dict[str, Any]:
        resp = await self.client.chat.completions.create(**request)
        return resp.model_dump()

    async def list_models(self) -> list[dict[str, Any]]:
        page = await self.client.models.list()
        return [m.model_dump() for m in page.data]


def _price(role_cfg: dict[str, Any], prompt: int, completion: int) -> float:
    return (prompt * role_cfg.get("price_in", 0) + completion * role_cfg.get("price_out", 0)) / 1_000_000


class LLM:
    def __init__(
        self,
        backend: Backend | None = None,
        cache: DiskCache | None = None,
        config: dict[str, Any] | None = None,
    ):
        self.cfg = config or load_config("models")
        self.cache = cache or DiskCache()
        self._backend = backend
        self._disabled: set[str] = set()

    # -- backend ---------------------------------------------------------------------------
    @property
    def backend(self) -> Backend:
        if self._backend is None:
            prov = self.cfg["provider"]
            key = env(prov.get("api_key_env", "NEBIUS_API_KEY"))
            if not key:
                raise LLMUnavailable("NEBIUS_API_KEY is not set")
            base_url = env("NEBIUS_BASE_URL", prov["base_url"])
            self._backend = OpenAIBackend(
                base_url, key, prov.get("timeout_s", 120), prov.get("max_retries", 4)
            )
        return self._backend

    def available(self) -> bool:
        if self._backend is not None:
            return True
        return bool(env(self.cfg["provider"].get("api_key_env", "NEBIUS_API_KEY")))

    def resolve_role(self, role: Role) -> tuple[str, dict[str, Any]]:
        """Return the (role, config) actually used, following configured fallbacks."""
        seen = set()
        current: str | None = role
        while current is not None and current not in seen:
            seen.add(current)
            if current not in self._disabled:
                return current, self.cfg["roles"][current]
            current = self.cfg.get("fallbacks", {}).get(current)
        raise LLMUnavailable(f"no model available for role {role!r}")

    def disable_role(self, role: str) -> None:
        self._disabled.add(role)

    def model_id(self, role: Role) -> str:
        return self.resolve_role(role)[1]["id"]

    # -- request building ------------------------------------------------------------------
    def _apply_reasoning(self, req: dict[str, Any], on: bool) -> None:
        mode = self.cfg.get("reasoning_switch", "chat_template_kwargs")
        if mode == "chat_template_kwargs":
            req.setdefault("extra_body", {})["chat_template_kwargs"] = {"enable_thinking": on}
        elif mode == "system_flag":
            flag = "/think" if on else "/no_think"
            msgs = req["messages"]
            if msgs and msgs[0]["role"] == "system":
                msgs[0] = {**msgs[0], "content": f"{flag}\n{msgs[0]['content']}"}
            else:
                msgs.insert(0, {"role": "system", "content": flag})

    async def chat(
        self,
        role: Role,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = None,
        reasoning: bool | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        json_mode: bool = False,
        meter: CostMeter | None = None,
        tag: str | None = None,
    ) -> LLMResult:
        if meter:
            meter.check()
        used_role, rcfg = self.resolve_role(role)
        if reasoning is None:
            reasoning = bool(rcfg.get("reasoning_default", False))
        req: dict[str, Any] = {
            "model": rcfg["id"],
            "messages": [dict(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens or rcfg.get("max_tokens", 4096),
        }
        if tools:
            req["tools"] = tools
            if tool_choice is not None:
                req["tool_choice"] = tool_choice
        if json_mode:
            req["response_format"] = {"type": "json_object"}
        self._apply_reasoning(req, reasoning)

        key = cache_key(req)
        t0 = time.monotonic()
        raw = self.cache.get(key)
        cached = raw is not None
        if raw is None:
            raw = await self._call_with_backoff(req)
            self.cache.put(key, raw)
        latency = 0.0 if cached else time.monotonic() - t0

        result = self._parse(raw, used_role, rcfg, latency, cached)
        if meter:
            await meter.record(
                CallRecord(
                    role=used_role,
                    model=rcfg["id"],
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    cost_usd=0.0 if cached else result.cost_usd,
                    latency_s=latency,
                    cached=cached,
                    tag=tag,
                    case_id=meter.case_id,
                )
            )
        return result

    async def _call_with_backoff(self, req: dict[str, Any]) -> dict[str, Any]:
        # The SDK already retries 429/5xx; this adds a short outer retry for transient
        # connection resets that surface as generic exceptions on long reasoning calls.
        delay = 2.0
        for attempt in range(3):
            try:
                return await self.backend.complete(req)
            except LLMUnavailable:
                raise
            except Exception as e:  # noqa: BLE001
                status = getattr(e, "status_code", None)
                if status in (400, 401, 403, 404, 422) or attempt == 2:
                    raise
                log.warning("LLM call failed (%s), retrying in %.0fs", type(e).__name__, delay)
                await asyncio.sleep(delay)
                delay *= 2
        raise AssertionError("unreachable")

    def _parse(
        self, raw: dict[str, Any], role: str, rcfg: dict[str, Any], latency: float, cached: bool
    ) -> LLMResult:
        choice = (raw.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        usage = raw.get("usage") or {}
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args_raw = fn.get("arguments") or "{}"
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
            except json.JSONDecodeError:
                args = {"__invalid_json__": args_raw}
            calls.append(
                ToolCall(
                    id=tc.get("id") or "",
                    name=fn.get("name", ""),
                    arguments=args,
                    raw_arguments=args_raw if isinstance(args_raw, str) else json.dumps(args_raw),
                )
            )
        pt, ct = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
        return LLMResult(
            role=role,
            model=rcfg["id"],
            content=msg.get("content") or "",
            tool_calls=calls,
            reasoning=msg.get("reasoning_content") or msg.get("reasoning"),
            prompt_tokens=pt,
            completion_tokens=ct,
            cost_usd=_price(rcfg, pt, ct),
            latency_s=latency,
            cached=cached,
            finish_reason=choice.get("finish_reason"),
        )

    # -- vision ----------------------------------------------------------------------------
    async def describe_images(
        self,
        prompt: str,
        images: list[bytes],
        *,
        mime: str = "image/png",
        system: str | None = None,
        meter: CostMeter | None = None,
        tag: str | None = None,
        json_mode: bool = False,
    ) -> LLMResult:
        """Omni is treated as image-only (PLAN A6): videos are turned into keyframes first."""
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for img in images:
            b64 = base64.b64encode(img).decode()
            content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}})
        messages: list[dict[str, Any]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": content})
        return await self.chat("omni", messages, meter=meter, tag=tag, json_mode=json_mode)


def result_to_dict(r: LLMResult) -> dict[str, Any]:
    return asdict(r)


_default: LLM | None = None


def get_llm() -> LLM:
    global _default
    if _default is None:
        _default = LLM()
    return _default


def set_llm(llm: LLM | None) -> None:
    global _default
    _default = llm
