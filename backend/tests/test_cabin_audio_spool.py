"""Audio archival streams through a temp file instead of accumulating in memory.

The bug this closes is invisible when it regresses — a session still works, it just
holds ~38MB per 20 minutes — so the memory property is asserted directly.
"""

from __future__ import annotations

import io
import os
import wave
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.storage import r2

from test_cabin_live import make_live, spooled, types_of

# ── the memory property ───────────────────────────────────────────────────


async def test_no_attribute_grows_with_session_length():
    """The whole point of the change: resident audio must not scale with duration."""
    live, _ = make_live()
    frame = b"\x00" * 1024
    for _ in range(4000):  # ~4MB, well past what the old list held for this long
        live._write_spool(frame)

    assert live._pcm_bytes == 4000 * 1024
    biggest = max(
        (len(v) for v in live.__dict__.values() if isinstance(v, (bytes, bytearray))),
        default=0,
    )
    assert biggest < 64 * 1024, "audio is being buffered in memory again"
    live._close_spool()


async def test_spool_preserves_byte_order():
    live, _ = make_live()
    live._write_spool(b"aaa")
    live._write_spool(b"bbb")
    assert spooled(live) == b"aaabbb"
    live._close_spool()


# ── WAV output ────────────────────────────────────────────────────────────


async def test_archive_streams_a_valid_wav_without_joining_in_memory():
    live, _ = make_live()
    for _ in range(200):
        live._write_spool(b"\x01\x02" * 512)  # 200 * 512 = 102400 frames

    captured = {}

    async def fake_upload(path, session_id, mime_type="audio/wav"):
        with open(path, "rb") as fh:
            captured["data"] = fh.read()
        captured["existed"] = os.path.exists(path)
        captured["path"] = path
        return "audio/sess-1/x.wav"

    with patch("app.cabin.live.r2.upload_audio_file", new=fake_upload):
        await live._archive_audio()

    with wave.open(io.BytesIO(captured["data"]), "rb") as wav_file:
        assert wav_file.getnchannels() == 1
        assert wav_file.getsampwidth() == 2
        assert wav_file.getframerate() == 16000
        assert wav_file.getnframes() == 200 * 512
    assert not os.path.exists(captured["path"]), "temp WAV left behind on success"
    live._close_spool()


async def test_temp_wav_is_removed_when_the_upload_fails():
    live, _ = make_live()
    live._write_spool(b"\x01\x02" * 800)
    seen = {}

    async def boom(path, session_id, mime_type="audio/wav"):
        seen["path"] = path
        raise RuntimeError("R2 upload failed")

    with patch("app.cabin.live.r2.upload_audio_file", new=boom):
        with pytest.raises(RuntimeError):
            await live._archive_audio()

    assert not os.path.exists(seen["path"]), "temp WAV leaked on the failure path"
    assert live.session.audio_key is None
    live._close_spool()


# ── degradation ───────────────────────────────────────────────────────────


async def test_a_spool_that_cannot_be_opened_does_not_end_the_session():
    """Losing the recording must never take the live transcript down with it."""
    live, ws = make_live()
    with patch(
        "app.cabin.live.tempfile.NamedTemporaryFile", side_effect=OSError("full")
    ):
        live._write_spool(b"\x01\x02")

    assert live._spool_failed is True
    assert live._pcm_bytes == 0
    # Later frames are dropped silently rather than retrying an exhausted disk.
    live._write_spool(b"\x03\x04")
    assert live._pcm_bytes == 0
    assert "error" not in types_of(ws)


async def test_teardown_skips_archival_when_nothing_was_recorded():
    """A doctor who connects and says nothing must not produce an empty upload."""
    live, _ = make_live()
    called = False

    async def fake_upload(path, session_id, mime_type="audio/wav"):
        nonlocal called
        called = True
        return "k"

    with patch("app.cabin.live.r2.upload_audio_file", new=fake_upload):
        await live._teardown()

    assert called is False
    assert live.session.audio_key is None


# ── the /tmp fallback ─────────────────────────────────────────────────────


async def test_upload_audio_file_falls_back_to_tmp_and_round_trips(
    monkeypatch, tmp_path
):
    """With R2 unconfigured the returned path must still satisfy download_audio, whose
    local branch keys off the /tmp prefix."""
    monkeypatch.setattr(settings, "R2_ENDPOINT_URL", "")
    monkeypatch.setattr(r2, "_s3_client", None)

    src = tmp_path / "audio.wav"
    src.write_bytes(b"RIFFfake-wav-body")

    key = await r2.upload_audio_file(str(src), "sess-1", mime_type="audio/wav")
    assert key.startswith("/tmp")
    assert key.endswith(".wav")
    try:
        assert await r2.download_audio(key) == b"RIFFfake-wav-body"
    finally:
        await r2.delete_audio(key)
    assert not os.path.exists(key)
