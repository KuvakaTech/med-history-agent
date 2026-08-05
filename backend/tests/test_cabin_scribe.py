"""ScribeStream tests — error classification, connection URL, and the reconnect paths.

Uses a fake websocket rather than touching ElevenLabs, so failure modes that are hard
to provoke against the live service (mid-stream drops, planned cutovers) are testable.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from websockets.exceptions import ConnectionClosed

from app.cabin.scribe import ScribeErrorClass, ScribeStream, classify_error
from app.core.config import settings


class FakeWS:
    """Minimal stand-in for a websockets client connection."""

    def __init__(self, messages: list[str] | None = None, closed_after: bool = True):
        self._messages = list(messages or [])
        self.sent: list[str] = []
        self.closed = False
        self._closed_after = closed_after

    async def recv(self) -> str:
        if self._messages:
            return self._messages.pop(0)
        if self._closed_after:
            raise ConnectionClosed(None, None)
        await asyncio.sleep(3600)

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True


class BlockingWS:
    """A socket whose recv() parks until the socket is closed, then raises
    ConnectionClosed — the behaviour a real pending recv() shows when the peer or a
    cutover closes it underneath. Needed to reproduce the rolling-reconnect race,
    which only bites while a recv() is already in flight."""

    def __init__(self, messages: list[str] | None = None):
        self._messages = list(messages or [])
        self._closed = asyncio.Event()
        self.closed = False
        self.sent: list[str] = []

    async def recv(self) -> str:
        if self._messages:
            return self._messages.pop(0)
        await self._closed.wait()
        raise ConnectionClosed(None, None)

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True
        self._closed.set()


# ── error classification ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    "event_type,expected",
    [
        ("auth_error", ScribeErrorClass.FATAL),
        ("quota_exceeded", ScribeErrorClass.FATAL),
        ("transcriber_error", ScribeErrorClass.RETRYABLE),
        ("session_time_limit_exceeded", ScribeErrorClass.RETRYABLE),
        ("rate_limited", ScribeErrorClass.TRANSIENT),
        ("queue_overflow", ScribeErrorClass.TRANSIENT),
        ("chunk_size_exceeded", ScribeErrorClass.OUR_BUG),
        ("insufficient_audio_activity", ScribeErrorClass.INFORMATIONAL),
        ("something_new_from_elevenlabs", ScribeErrorClass.UNKNOWN),
    ],
)
def test_error_classification(event_type, expected):
    assert classify_error(event_type) == expected


def test_quota_exceeded_is_not_retried():
    """Retrying a quota error just burns the clock — it must be terminal."""
    assert classify_error("quota_exceeded") == ScribeErrorClass.FATAL


# ── connection URL ────────────────────────────────────────────────────────


def test_connect_url_carries_required_params():
    stream = ScribeStream(
        secondary_languages=["hi", "en", "mr", "gu"], keyterms=["metformin"]
    )
    url = stream._connect_url()
    assert settings.ELEVENLABS_STT_MODEL in url
    assert "audio_format=pcm_16000" in url
    assert "include_language_detection=true" in url
    assert "filter_background_audio=" in url  # the denoiser
    assert "hi%2Cen%2Cmr%2Cgu" in url


def test_keyterms_capped_at_fifty():
    """ElevenLabs rejects more than 50 keyterms; truncate rather than fail the connect."""
    stream = ScribeStream(keyterms=[f"drug{i}" for i in range(80)])
    assert len(stream._keyterms) == 50


def test_no_verbatim_reflects_config(monkeypatch):
    monkeypatch.setattr(settings, "CABIN_STT_NO_VERBATIM", False)
    assert "no_verbatim=false" in ScribeStream()._connect_url()
    monkeypatch.setattr(settings, "CABIN_STT_NO_VERBATIM", True)
    assert "no_verbatim=true" in ScribeStream()._connect_url()


# ── audio framing ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_audio_base64_encodes_pcm():
    stream = ScribeStream()
    fake = FakeWS()
    stream._ws = fake
    await stream.send_audio(b"\x01\x02\x03\x04")
    payload = json.loads(fake.sent[0])
    assert payload["type"] == "input_audio_chunk"
    import base64

    assert base64.b64decode(payload["audio_chunk"]) == b"\x01\x02\x03\x04"


@pytest.mark.asyncio
async def test_send_audio_without_connection_raises():
    with pytest.raises(RuntimeError):
        await ScribeStream().send_audio(b"\x00")


# ── event stream ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_events_yields_transcripts_then_ends_on_fatal():
    stream = ScribeStream()
    stream._ws = FakeWS(
        [
            json.dumps({"type": "partial_transcript", "text": "mujhe bukhar"}),
            json.dumps({"type": "committed_transcript", "text": "mujhe bukhar hai"}),
            json.dumps({"type": "auth_error"}),
        ],
        closed_after=False,
    )
    events = [e async for e in stream.events()]
    assert [e.type for e in events] == [
        "partial_transcript",
        "committed_transcript",
        "auth_error",
    ]
    assert events[-1].error_class == ScribeErrorClass.FATAL


@pytest.mark.asyncio
async def test_malformed_json_is_skipped_not_fatal():
    stream = ScribeStream()
    stream._ws = FakeWS(
        [
            "this is not json",
            json.dumps({"type": "committed_transcript", "text": "ok"}),
        ],
        closed_after=False,
    )
    events = []
    async for event in stream.events():
        events.append(event)
        if len(events) == 1:
            break
    assert events[0].type == "committed_transcript"


@pytest.mark.asyncio
async def test_rolling_reconnect_does_not_trigger_a_second_reconnect(monkeypatch):
    """Regression: the cutover happens while events() is already parked in recv() on
    the old socket. Closing it wakes that recv() with ConnectionClosed, and without the
    rolling-over flag events() reads a deliberate swap as an unexpected drop — opening
    a third socket and throwing away the replacement we just made.

    The consumer must be blocked in recv() *before* the cutover, or the race never
    happens and the test proves nothing.
    """
    monkeypatch.setattr("app.cabin.scribe.RECONNECT_BACKOFFS", (0, 0, 0))

    stream = ScribeStream()
    original = BlockingWS()  # no messages: recv() parks until closed
    replacement = BlockingWS(
        [json.dumps({"type": "committed_transcript", "text": "after cutover"})]
    )
    stream._ws = original

    opened: list[BlockingWS] = []

    async def fake_open():
        opened.append(replacement)
        return replacement

    monkeypatch.setattr(stream, "_open", fake_open)

    received: list = []

    async def consume():
        async for event in stream.events():
            received.append(event)
            if event.type == "committed_transcript":
                return

    consumer = asyncio.create_task(consume())
    # Let the consumer reach the parked recv() on the original socket.
    await asyncio.sleep(0.05)
    assert not consumer.done()

    assert await stream.rolling_reconnect() is True
    assert original.closed is True
    assert stream._ws is replacement

    await asyncio.wait_for(consumer, timeout=1.0)

    assert (
        len(opened) == 1
    ), "a second socket was opened — the cutover was misread as a drop"
    assert [e.type for e in received] == [
        "committed_transcript"
    ], f"expected a clean cutover, got {[e.type for e in received]}"
    assert received[0].data["text"] == "after cutover"


@pytest.mark.asyncio
async def test_rolling_reconnect_keeps_old_socket_when_open_fails(monkeypatch):
    stream = ScribeStream()
    original = FakeWS(closed_after=False)
    stream._ws = original

    async def failing_open():
        raise OSError("connection refused")

    monkeypatch.setattr(stream, "_open", failing_open)

    assert await stream.rolling_reconnect() is False
    assert stream._ws is original, "a failed cutover must not drop the working socket"
    assert original.closed is False


@pytest.mark.asyncio
async def test_unexpected_drop_reconnects_then_gives_up(monkeypatch):
    """Three failed attempts, then a fatal_disconnect rather than an infinite loop."""
    stream = ScribeStream()
    stream._ws = FakeWS(closed_after=True)

    async def failing_open():
        raise OSError("down")

    monkeypatch.setattr(stream, "_open", failing_open)
    monkeypatch.setattr("app.cabin.scribe.RECONNECT_BACKOFFS", (0, 0, 0))

    events = [e async for e in stream.events()]
    assert [e.type for e in events] == ["reconnecting", "fatal_disconnect"]
    assert events[-1].error_class == ScribeErrorClass.FATAL
