"""Pedagogical summariser service.

Supports three modes:
  • local  – Ollama endpoint (default, no API key needed)
  • openai – OpenAI-compatible REST endpoint
  • gemini – Google Generative Language API

For long content the text is chunked, each chunk summarised individually,
and the partial summaries synthesised in a final consolidation call.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from app.core.config import Settings
from app.core.exceptions import OllamaUnavailableError, SummarisationError
from app.services.chunker import Chunk

logger = logging.getLogger(__name__)

_PEDAGOGICAL_SYSTEM = (
    "You are an expert educational content designer specialising in adult learning. "
    "Create pedagogically rich summaries: open with the central learning objective, "
    "list 4-6 key concepts as bullet points, note connections to other topics, "
    "and close with a sentence on why this content matters. "
    "Write for spoken audio: no Markdown links, no raw file names."
)

_CHUNK_SYSTEM = (
    "You are an educational content assistant. Extract key learning points from this "
    "excerpt. Return a concise bullet list (4-8 bullets). Focus on concepts and skills."
)

_SYNTHESIS_SYSTEM = (
    "You are an expert educational content designer. Synthesise the partial summaries "
    "below into one cohesive pedagogical summary: 1 sentence for the learning objective, "
    "4-6 bullet points for key concepts, 1 sentence on relevance. Write for speech output."
)


class SummariserService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._provider = settings.ai_summary_provider.strip().lower()

    # ── Public API ────────────────────────────────────────────────────────────

    async def summarise_week(
        self,
        chunks: list[Chunk],
        language: str = "de",
    ) -> str:
        """Return a single pedagogical summary for the provided chunks."""
        if not chunks:
            return ""
        lang_instr = f"Respond in language '{language}'."

        if len(chunks) == 1:
            return await self._single_pass(chunks[0].content, lang_instr)

        # Multi-pass: summarise each chunk then synthesise.
        logger.info("Multi-pass summarisation: %d chunks", len(chunks))
        partial: list[str] = []
        for i, chunk in enumerate(chunks, start=1):
            logger.debug("Chunk %d/%d (%d chars)", i, len(chunks), chunk.char_count)
            text = f"{chunk.heading_path}\n\n{chunk.content}" if chunk.heading_path else chunk.content
            summary = await self._chat(
                system=f"{_CHUNK_SYSTEM} {lang_instr}",
                user=f"Excerpt:\n{text}",
                max_tokens=300,
            )
            partial.append(summary)

        combined = "\n\n---\n\n".join(partial)
        return await self._chat(
            system=f"{_SYNTHESIS_SYSTEM} {lang_instr}",
            user=f"Partial summaries:\n{combined}",
            max_tokens=self._settings.local_llm_max_tokens,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _single_pass(self, content: str, lang_instr: str) -> str:
        return await self._chat(
            system=f"{_PEDAGOGICAL_SYSTEM} {lang_instr}",
            user=f"Length: about 140-220 words total.\nCourse content:\n{content}",
            max_tokens=self._settings.local_llm_max_tokens,
        )

    async def _chat(self, system: str, user: str, max_tokens: int = 600) -> str:
        if self._provider == "gemini":
            return await self._call_gemini(system, user, max_tokens)
        # Both "local" and "openai" use the OpenAI chat completions schema.
        return await self._call_openai_compat(system, user, max_tokens)

    async def _call_openai_compat(self, system: str, user: str, max_tokens: int) -> str:
        base_url = (
            self._settings.ai_summary_base_url.rstrip("/")
            or self._settings.ollama_base_url.rstrip("/")
        )
        model = self._settings.ai_summary_model or self._settings.ollama_model
        api_key = self._settings.openai_api_key or "ollama"

        payload: dict[str, Any] = {
            "model": model,
            "temperature": self._settings.local_llm_temperature,
            "max_tokens": max_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        url = f"{base_url}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self._settings.local_llm_timeout_seconds) as client:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
        except httpx.ConnectError as exc:
            raise OllamaUnavailableError(
                f"Cannot reach LLM endpoint at {base_url}: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise SummarisationError(
                f"LLM endpoint returned HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc

        data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise SummarisationError("LLM returned no choices")
        content = ((choices[0].get("message") or {}).get("content") or "").strip()
        if not content:
            raise SummarisationError("LLM returned empty content")
        return content

    async def _call_gemini(self, system: str, user: str, max_tokens: int) -> str:
        from urllib.parse import urlencode
        api_key = self._settings.gemini_api_key or self._settings.google_api_key
        if not api_key:
            raise SummarisationError("GEMINI_API_KEY is required for Gemini provider")
        model = self._settings.ai_summary_model or "gemini-1.5-flash"
        base = "https://generativelanguage.googleapis.com/v1beta"
        url = f"{base}/models/{model}:generateContent?key={api_key}"
        payload = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": self._settings.local_llm_temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise SummarisationError(
                f"Gemini returned HTTP {exc.response.status_code}: {exc.response.text[:300]}"
            ) from exc
        candidates = resp.json().get("candidates") or []
        if not candidates:
            raise SummarisationError("Gemini returned no candidates")
        parts = ((candidates[0].get("content") or {}).get("parts") or [])
        text = "\n".join((p.get("text") or "").strip() for p in parts if p.get("text")).strip()
        if not text:
            raise SummarisationError("Gemini returned empty text")
        return text
