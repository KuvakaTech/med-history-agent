"""Async LLM client — Anthropic preferred, Groq fallback. No LlamaIndex overhead."""
from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncGenerator, Type

from pydantic import BaseModel

from app.agent import usage
from app.core.config import settings

log = logging.getLogger(__name__)


def _extract_json(text: str, schema: Type[BaseModel]) -> BaseModel:
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    obj = re.search(r"\{.*\}", text, re.DOTALL)
    for candidate in filter(None, [
        fence.group(1) if fence else None,
        obj.group(0) if obj else None,
        text.strip(),
    ]):
        try:
            return schema.model_validate_json(candidate)
        except Exception:
            try:
                return schema.model_validate(json.loads(candidate))
            except Exception:
                continue
    raise ValueError(f"Could not parse LLM response into {schema.__name__}: {text[:300]}")


async def complete(prompt: str, system: str = "", temperature: float = 0.3, fast: bool = False) -> str:
    """Plain text completion. Anthropic primary, Groq fallback."""
    if settings.ANTHROPIC_API_KEY:
        try:
            return await _anthropic_complete(prompt, system, temperature, fast=fast)
        except Exception as exc:
            log.warning("Anthropic complete failed (%s), falling back to Groq", exc)
    if settings.GROQ_API_KEY:
        return await _groq_complete(prompt, system, temperature)
    return await _gemini_complete(prompt, temperature, fast=fast)


async def complete_structured(
    prompt: str,
    schema: Type[BaseModel],
    system: str = "",
    temperature: float = 0.3,
    fast: bool = False,
    max_tokens: int = 512,
) -> BaseModel:
    """Structured completion returning a validated Pydantic model. Anthropic primary, Groq fallback."""
    if settings.ANTHROPIC_API_KEY:
        try:
            return await _anthropic_structured(prompt, schema, system, temperature, fast=fast, max_tokens=max_tokens)
        except Exception as exc:
            log.warning("Anthropic structured failed (%s), falling back to Groq", exc)
    if settings.GROQ_API_KEY:
        return await _groq_structured(prompt, schema, system, temperature, max_tokens=max_tokens)
    return await _gemini_structured(prompt, schema, temperature, fast=fast)


async def stream_complete(
    prompt: str, system: str = "", fast: bool = True
) -> AsyncGenerator[str, None]:
    """Stream text tokens. Anthropic primary, Groq fallback — matches complete()/complete_structured().

    If Anthropic errors before any token was yielded, we transparently retry on Groq so the
    caller — and the patient — never sees the raw provider error. Once tokens have started
    streaming from one provider we can no longer switch, since the caller has already
    displayed a partial answer.
    """
    started = False
    if settings.ANTHROPIC_API_KEY:
        try:
            async for token in _anthropic_stream(prompt, system, fast=fast):
                started = True
                yield token
            return
        except Exception as exc:
            if started:
                raise
            log.warning("Anthropic stream failed (%s), falling back to Groq", exc)

    if settings.GROQ_API_KEY:
        async for token in _groq_stream(prompt, system):
            started = True
            yield token
        return

    async for token in _gemini_stream(prompt, system, fast=fast):
        yield token


# ─────────────────────────────────────────────
# Groq  (OpenAI-compatible)
# ─────────────────────────────────────────────

def _record_groq(data: dict) -> None:
    u = (data or {}).get("usage") or {}
    usage.record(
        "groq",
        settings.GROQ_MODEL,
        u.get("prompt_tokens", 0) or 0,
        u.get("completion_tokens", 0) or 0,
    )


def _record_gemini(model: str, resp: Any) -> None:
    u = getattr(resp, "usage_metadata", None)
    if u is None:
        return
    usage.record(
        "gemini",
        model,
        getattr(u, "prompt_token_count", 0) or 0,
        getattr(u, "candidates_token_count", 0) or 0,
    )


async def _groq_complete(prompt: str, system: str, temperature: float, max_tokens: int = 1024) -> str:
    import httpx

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.GROQ_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
        )
        response.raise_for_status()
        data = response.json()
        _record_groq(data)
        return data["choices"][0]["message"]["content"]


async def _groq_structured(
    prompt: str, schema: Type[BaseModel], system: str, temperature: float, max_tokens: int = 512
) -> BaseModel:
    import httpx

    # json_object mode requires the word "JSON" in the conversation and works across
    # Groq-hosted models, unlike tool calling; the schema goes in the system prompt.
    schema_instruction = (
        f"Respond ONLY with a JSON object matching this JSON schema:\n"
        f"{json.dumps(schema.model_json_schema())}"
    )
    full_system = f"{system}\n\n{schema_instruction}" if system else schema_instruction
    messages = [
        {"role": "system", "content": full_system},
        {"role": "user", "content": prompt},
    ]

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.GROQ_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        data = response.json()
        _record_groq(data)
        return _extract_json(data["choices"][0]["message"]["content"], schema)


async def _groq_stream(prompt: str, system: str) -> AsyncGenerator[str, None]:
    import httpx

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    async with httpx.AsyncClient(timeout=60) as client:
        async with client.stream(
            "POST",
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": settings.GROQ_MODEL, "messages": messages, "stream": True, "temperature": 0.4},
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"].get("content", "")
                    if delta:
                        yield delta
                except Exception:
                    continue


# ─────────────────────────────────────────────
# Gemini
# ─────────────────────────────────────────────

def _gemini_model(fast: bool) -> str:
    return settings.GEMINI_FAST_MODEL if fast else settings.GEMINI_MODEL


async def _gemini_complete(prompt: str, temperature: float, fast: bool = False) -> str:
    from google import genai
    from google.genai import types

    client = genai.AsyncClient(api_key=settings.GOOGLE_API_KEY)
    resp = await client.aio.models.generate_content(
        model=_gemini_model(fast),
        contents=prompt,
        config=types.GenerateContentConfig(temperature=temperature),
    )
    _record_gemini(_gemini_model(fast), resp)
    return resp.text


async def _gemini_structured(
    prompt: str, schema: Type[BaseModel], temperature: float, fast: bool = False
) -> BaseModel:
    from google import genai
    from google.genai import types

    client = genai.AsyncClient(api_key=settings.GOOGLE_API_KEY)
    try:
        resp = await client.aio.models.generate_content(
            model=_gemini_model(fast),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=schema,
                temperature=temperature,
            ),
        )
        _record_gemini(_gemini_model(fast), resp)
        return _extract_json(resp.text, schema)
    except Exception as exc:
        log.warning("Gemini structured failed (%s), falling back to plain", exc)
        resp = await client.aio.models.generate_content(
            model=_gemini_model(fast),
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=temperature,
            ),
        )
        _record_gemini(_gemini_model(fast), resp)
        return _extract_json(resp.text, schema)


async def _gemini_stream(prompt: str, system: str, fast: bool = True) -> AsyncGenerator[str, None]:
    from google import genai
    from google.genai import types

    client = genai.AsyncClient(api_key=settings.GOOGLE_API_KEY)
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    async for chunk in await client.aio.models.generate_content_stream(
        model=_gemini_model(fast),
        contents=full_prompt,
        config=types.GenerateContentConfig(temperature=0.4),
    ):
        if chunk.text:
            yield chunk.text


# ─────────────────────────────────────────────
# Anthropic
# ─────────────────────────────────────────────

def _anthropic_model(fast: bool) -> str:
    return settings.ANTHROPIC_FAST_MODEL if fast else settings.ANTHROPIC_MODEL


def _record_anthropic(model: str, resp: Any) -> None:
    """Read token usage off a response. Every field is read defensively — a telemetry
    gap must never raise into a clinical path."""
    u = getattr(resp, "usage", None)
    if u is None:
        return
    usage.record(
        "anthropic",
        model,
        getattr(u, "input_tokens", 0) or 0,
        getattr(u, "output_tokens", 0) or 0,
    )


async def _anthropic_complete(
    prompt: str, system: str, temperature: float, fast: bool = False
) -> str:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    kwargs: dict[str, Any] = dict(
        model=_anthropic_model(fast),
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    if system:
        kwargs["system"] = system
    resp = await client.messages.create(**kwargs)
    _record_anthropic(kwargs["model"], resp)
    return resp.content[0].text  # type: ignore[index]


async def _anthropic_structured(
    prompt: str, schema: Type[BaseModel], system: str, temperature: float, fast: bool = False, max_tokens: int = 512
) -> BaseModel:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    tool_schema = schema.model_json_schema()
    tool_name = schema.__name__

    kwargs: dict[str, Any] = dict(
        model=_anthropic_model(fast),
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
        tools=[{
            "name": tool_name,
            "description": f"Return a {tool_name} object",
            "input_schema": tool_schema,
        }],
        tool_choice={"type": "tool", "name": tool_name},
    )
    if system:
        kwargs["system"] = system

    try:
        resp = await client.messages.create(**kwargs)
        _record_anthropic(kwargs["model"], resp)
        tool_block = next(b for b in resp.content if b.type == "tool_use")
        return schema.model_validate(tool_block.input)
    except Exception as exc:
        log.warning("Anthropic structured failed (%s), falling back to plain", exc)
        kwargs.pop("tools")
        kwargs.pop("tool_choice")
        resp = await client.messages.create(**kwargs)
        # The forced-tool attempt above may already have been billed; both are recorded.
        _record_anthropic(kwargs["model"], resp)
        return _extract_json(resp.content[0].text, schema)  # type: ignore[index]


async def _anthropic_stream(
    prompt: str, system: str, fast: bool = True
) -> AsyncGenerator[str, None]:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    kwargs: dict[str, Any] = dict(
        model=_anthropic_model(fast),
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    if system:
        kwargs["system"] = system
    async with client.messages.stream(**kwargs) as stream:
        async for text in stream.text_stream:
            yield text
