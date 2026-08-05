"""Token-usage plumbing and cost arithmetic.

The load-bearing property is that this is invisible to callers that don't opt in: six
modules call llm.complete/complete_structured and none of them changed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.agent import llm, usage
from app.core.config import settings


class FakeUsage:
    def __init__(self, input_tokens=100, output_tokens=50):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class FakeBlock:
    type = "text"

    def __init__(self, text="hello"):
        self.text = text


class FakeResponse:
    def __init__(self, usage_obj=FakeUsage()):
        self.content = [FakeBlock()]
        self.usage = usage_obj


@pytest.fixture
def sink():
    calls: list[usage.Call] = []
    usage.bind(calls)
    yield calls
    usage.bind(None)  # type: ignore[arg-type]


# ── the no-op guarantee ───────────────────────────────────────────────────


def test_record_without_a_sink_is_a_noop():
    """The backward-compatibility contract: the questionnaire path never binds a sink,
    so recording must be inert rather than raising or accumulating."""
    usage.bind(None)  # type: ignore[arg-type]
    usage.record("anthropic", "claude-haiku-4-5", 10, 5)  # must not raise


# ── collection ────────────────────────────────────────────────────────────


def test_a_bound_sink_collects(sink):
    usage.record("anthropic", "claude-haiku-4-5", 10, 5)
    assert len(sink) == 1
    assert sink[0].model == "claude-haiku-4-5"
    assert sink[0].input_tokens == 10


async def test_child_tasks_record_into_the_sink_bound_by_their_parent():
    """The property the design rests on: create_task copies the context, and the bound
    list is shared by reference, so a session's four worker tasks report into it."""
    calls: list[usage.Call] = []
    usage.bind(calls)

    async def worker(n: int) -> None:
        usage.record("anthropic", "claude-haiku-4-5", n, n)

    await asyncio.gather(*(asyncio.create_task(worker(i)) for i in range(1, 4)))
    assert sorted(c.input_tokens for c in calls) == [1, 2, 3]
    usage.bind(None)  # type: ignore[arg-type]


async def test_two_concurrent_sessions_do_not_mix_totals():
    """Two consultations on one worker each get their own context."""
    results: dict[str, list[usage.Call]] = {}

    async def session(name: str, tokens: int) -> None:
        calls: list[usage.Call] = []
        usage.bind(calls)
        await asyncio.sleep(0)
        usage.record("anthropic", "claude-haiku-4-5", tokens, tokens)
        results[name] = calls

    await asyncio.gather(
        asyncio.create_task(session("a", 10)), asyncio.create_task(session("b", 20))
    )
    assert [c.input_tokens for c in results["a"]] == [10]
    assert [c.input_tokens for c in results["b"]] == [20]


# ── pricing ───────────────────────────────────────────────────────────────


def test_price_resolves_by_longest_prefix():
    """The config pins a dated Haiku id, which has to price against its family."""
    assert usage.usd("claude-haiku-4-5-20251001", 1_000_000, 0) == pytest.approx(1.00)
    assert usage.usd("claude-sonnet-4-6", 0, 1_000_000) == pytest.approx(15.00)


def test_an_unpriced_model_costs_zero_but_keeps_exact_tokens(sink):
    """Never guess a rate: a plausible-looking wrong number is worse than a visible
    gap, because nobody re-checks it."""
    usage.record("groq", "llama-3.3-70b-versatile", 1000, 500)
    totals = usage.summarize(sink)
    assert totals.usd == 0.0
    assert totals.input_tokens == 1000
    assert totals.output_tokens == 500


def test_summarize_totals_calls_and_tokens(sink):
    usage.record("anthropic", "claude-haiku-4-5", 1_000_000, 1_000_000)
    usage.record("anthropic", "claude-sonnet-4-6", 1_000_000, 0)
    totals = usage.summarize(sink)
    assert totals.calls == 2
    assert totals.input_tokens == 2_000_000
    # Haiku 1+5, Sonnet 3 in
    assert totals.usd == pytest.approx(1.00 + 5.00 + 3.00)


def test_inr_uses_the_configured_rate(monkeypatch):
    monkeypatch.setattr(settings, "LLM_USD_TO_INR", 90.0)
    assert usage.inr(2.0) == pytest.approx(180.0)


# ── provider integration ──────────────────────────────────────────────────


async def test_anthropic_complete_still_returns_a_plain_string(sink, monkeypatch):
    """The contract that keeps all six untouched callers working."""
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "test-key")

    class FakeMessages:
        async def create(self, **kwargs):
            return FakeResponse()

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    with patch("anthropic.AsyncAnthropic", FakeClient):
        result = await llm.complete("hi", fast=True)

    assert result == "hello"
    assert len(sink) == 1
    assert sink[0].input_tokens == 100
    assert sink[0].output_tokens == 50


async def test_a_response_without_usage_does_not_break_the_completion(
    sink, monkeypatch
):
    """A provider SDK shape change must degrade to no telemetry, never an exception in
    a clinical path."""
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "test-key")

    class NoUsageResponse:
        content = [FakeBlock()]

    class FakeMessages:
        async def create(self, **kwargs):
            return NoUsageResponse()

    class FakeClient:
        def __init__(self, **kwargs):
            self.messages = FakeMessages()

    with patch("anthropic.AsyncAnthropic", FakeClient):
        result = await llm.complete("hi", fast=True)

    assert result == "hello"
    assert sink == []
