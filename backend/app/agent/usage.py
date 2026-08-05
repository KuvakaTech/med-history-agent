"""Per-call LLM token usage, collected out-of-band.

Threading usage through return values would change the signature of every
complete()/complete_structured()/stream_complete() call site — fourteen of them, in six
modules that never asked for telemetry. A contextvars sink keeps those signatures
untouched: when no sink is bound, record() is a no-op, so the questionnaire path behaves
exactly as it did before.

A ContextVar is also correct under concurrency. asyncio.create_task copies the current
context, and the bound value is a mutable list captured by reference, so appends made by
a session's child tasks land in the list its run() bound. Two consultations on the same
worker each run in their own task, and therefore their own context, so their totals
cannot mix.
"""

from __future__ import annotations

import contextvars
import logging
from dataclasses import dataclass

from app.core.config import settings

log = logging.getLogger(__name__)

# USD per 1M tokens, (input, output), keyed by model family. Looked up by longest
# prefix match so a dated id ("claude-haiku-4-5-20251001") resolves against its family.
#
# Only models whose list price has been verified appear here. An unpriced model still
# has its tokens counted exactly and contributes 0.0 to the cost — a spend figure built
# from a guessed rate is worse than one that is visibly incomplete, because nobody
# checks a number that looks plausible.
_PRICES: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-6": (3.00, 15.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

_unpriced_seen: set[str] = set()

_sink: contextvars.ContextVar[list["Call"] | None] = contextvars.ContextVar(
    "llm_usage_sink", default=None
)


@dataclass
class Call:
    provider: str
    model: str
    input_tokens: int
    output_tokens: int


@dataclass
class Totals:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0


def bind(sink: list[Call]) -> None:
    """Route usage recorded by this task, and tasks it spawns, into `sink`."""
    _sink.set(sink)


def record(provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
    """Record one provider call. A no-op when no sink is bound."""
    sink = _sink.get()
    if sink is None:
        return
    sink.append(Call(provider, model, int(input_tokens or 0), int(output_tokens or 0)))


def _rate(model: str) -> tuple[float, float] | None:
    match: str | None = None
    for family in _PRICES:
        if model.startswith(family) and (match is None or len(family) > len(match)):
            match = family
    return _PRICES[match] if match else None


def usd(model: str, input_tokens: int, output_tokens: int) -> float:
    rate = _rate(model)
    if rate is None:
        if model not in _unpriced_seen:
            _unpriced_seen.add(model)
            log.info("No price on file for model %s; counting tokens only.", model)
        return 0.0
    return (input_tokens * rate[0] + output_tokens * rate[1]) / 1_000_000


def summarize(calls: list[Call]) -> Totals:
    totals = Totals()
    for call in calls:
        totals.calls += 1
        totals.input_tokens += call.input_tokens
        totals.output_tokens += call.output_tokens
        totals.usd += usd(call.model, call.input_tokens, call.output_tokens)
    return totals


def inr(usd_amount: float) -> float:
    return usd_amount * settings.LLM_USD_TO_INR
