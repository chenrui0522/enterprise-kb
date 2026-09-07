from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from openai import AsyncOpenAI

from app.core.config import Settings
from app.core.errors import UpstreamError
from app.providers.base import LLMProvider


class DeepSeekProvider(LLMProvider):
    """DeepSeek generation model via its OpenAI-compatible API."""

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            timeout=120.0,
            max_retries=2,
        )
        self._model = settings.llm_model
        self._temperature = settings.llm_temperature

    async def complete(self, *, system: str, user: str, temperature: float | None = None) -> str:
        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self._temperature if temperature is None else temperature,
        )
        return response.choices[0].message.content or ""

    async def complete_json(self, *, system: str, user: str, temperature: float | None = None) -> dict:
        last_error: Exception | None = None
        for attempt in range(3):
            if attempt:
                await asyncio.sleep(1.0)
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=self._temperature if temperature is None else temperature,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content or ""
            if not raw.strip():
                last_error = UpstreamError("LLM 返回了空响应")
                continue
            try:
                data = json.loads(_strip_code_fence(raw))
            except json.JSONDecodeError as exc:
                last_error = UpstreamError(f"LLM 返回了非法 JSON：{raw[:200]}")
                continue
            if not isinstance(data, dict):
                last_error = UpstreamError("LLM JSON 输出必须是对象")
                continue
            return data
        assert last_error is not None
        raise last_error

    async def stream(self, *, system: str, user: str, temperature: float | None = None) -> AsyncIterator[str]:
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=self._temperature if temperature is None else temperature,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text
