from __future__ import annotations

from app.agent import llm

DETECT_PROMPT = """Detect the primary language of the following text.
Return ONLY the ISO 639-1 two-letter language code (e.g. 'en', 'hi', 'ar', 'fr').

Text:
{text}"""

TRANSLATE_PROMPT = """Translate the following text from {source_lang} to {target_lang}.
Return only the translated text, nothing else.

Text:
{text}"""


class TranslationService:
    async def detect_language(self, text: str) -> str:
        prompt = DETECT_PROMPT.format(text=text[:2000])
        result = await llm.complete(prompt)
        return result.strip().lower()[:5]

    async def translate(self, text: str, source_lang: str, target_lang: str) -> str:
        if source_lang == target_lang:
            return text
        prompt = TRANSLATE_PROMPT.format(
            source_lang=source_lang,
            target_lang=target_lang,
            text=text,
        )
        return await llm.complete(prompt)
