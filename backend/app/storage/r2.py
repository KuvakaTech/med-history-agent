"""Cloudflare R2 storage (S3-compatible). Falls back to local /tmp if R2 is not configured."""
from __future__ import annotations

import asyncio
import os
import uuid
from functools import partial

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import settings

_s3_client = None


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


async def upload_audio(data: bytes, session_id: str, suffix: str = ".wav") -> str:
    """Upload audio bytes to R2. Returns a key (R2) or local path (fallback)."""
    key = f"audio/{session_id}/{uuid.uuid4().hex}{suffix}"
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
                ContentType="audio/wav",
            ),
        )
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
