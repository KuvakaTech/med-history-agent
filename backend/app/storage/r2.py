"""Cloudflare R2 storage (S3-compatible). Falls back to local /tmp if R2 is not configured."""
from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from functools import partial

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

_s3_client = None

# S3 requires every part except the last to be at least 5MiB, and R2 requires them all
# to be the same size.
_PART_BYTES = 8 * 1024 * 1024

# Audio formats we accept from browsers/uploads. Deepgram auto-detects all of these.
_MIME_EXT = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
}


def _normalize_mime(mime_type: str) -> str:
    """Strip codec params, e.g. 'audio/webm;codecs=opus' -> 'audio/webm'."""
    return mime_type.split(";")[0].strip().lower()


def audio_suffix(mime_type: str) -> str:
    """File extension for a given audio mime type (default .webm)."""
    return _MIME_EXT.get(_normalize_mime(mime_type), ".webm")


def _get_s3():
    global _s3_client
    if _s3_client is None and settings.R2_ENDPOINT_URL:
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.R2_ENDPOINT_URL,
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )
    return _s3_client


async def upload_audio(data: bytes, session_id: str, mime_type: str = "audio/webm") -> str:
    """Upload audio bytes to R2. Returns a key (R2) or local path (fallback)."""
    key = f"audio/{session_id}/{uuid.uuid4().hex}{audio_suffix(mime_type)}"
    s3 = _get_s3()
    if s3 is None:
        # Fallback: write to temp dir
        path = f"/tmp/{key.replace('/', '_')}"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: open(path, "wb").write(data))
        return path

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            partial(
                s3.put_object,
                Bucket=settings.R2_BUCKET_NAME,
                Key=key,
                Body=data,
                ContentType=_normalize_mime(mime_type) or "application/octet-stream",
            ),
        )
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"R2 upload failed: {exc}") from exc

    return key


async def upload_audio_file(
    path: str, session_id: str, mime_type: str = "audio/webm"
) -> str:
    """Upload audio from a local file. Streams the body instead of holding it in memory,
    and boto3 splits it into a multipart upload above its threshold. Returns a key (R2)
    or a local path (fallback), same as upload_audio."""
    key = f"audio/{session_id}/{uuid.uuid4().hex}{audio_suffix(mime_type)}"
    s3 = _get_s3()
    loop = asyncio.get_event_loop()

    if s3 is None:
        # Fallback: move it under /tmp, where download_audio and delete_audio treat the
        # returned path as a local file.
        dest = f"/tmp/{key.replace('/', '_')}"
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        await loop.run_in_executor(None, partial(shutil.copyfile, path, dest))
        return dest

    def _upload() -> None:
        with open(path, "rb") as fh:
            s3.upload_fileobj(
                fh,
                settings.R2_BUCKET_NAME,
                key,
                ExtraArgs={
                    "ContentType": _normalize_mime(mime_type)
                    or "application/octet-stream"
                },
                # R2 requires every non-final part to be the same size; a single
                # explicit chunk size keeps the transfer manager uniform.
                Config=TransferConfig(multipart_chunksize=_PART_BYTES),
            )

    try:
        await loop.run_in_executor(None, _upload)
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"R2 upload failed: {exc}") from exc

    return key


async def download_audio(key: str) -> bytes:
    """Download audio from R2 by key, or read local file on fallback."""
    s3 = _get_s3()
    if s3 is None or key.startswith("/tmp"):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: open(key, "rb").read())

    loop = asyncio.get_event_loop()
    try:
        response = await loop.run_in_executor(
            None,
            partial(s3.get_object, Bucket=settings.R2_BUCKET_NAME, Key=key),
        )
        return response["Body"].read()
    except (BotoCoreError, ClientError) as exc:
        raise RuntimeError(f"R2 download failed: {exc}") from exc


async def delete_audio(key: str) -> None:
    s3 = _get_s3()
    if s3 is None or key.startswith("/tmp"):
        try:
            os.remove(key)
        except OSError:
            pass
        return

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(
            None,
            partial(s3.delete_object, Bucket=settings.R2_BUCKET_NAME, Key=key),
        )
    except (BotoCoreError, ClientError):
        pass
