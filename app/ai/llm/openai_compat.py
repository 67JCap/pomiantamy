"""Любой OpenAI-compatible API: OpenRouter, OpenAI, Together, DeepSeek...

Тот же контракт ILLM — облако как drop-in замена локальной модели (fallback).
API-ключ берётся из переменной окружения (api_key_env), НИКОГДА из кода.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx

from app.core.interfaces import ILLM
from app.core.registry import register


@register("llm", "openai_compat")
class OpenAICompatLLM(ILLM):
    def __init__(self, model: str, base_url: str = "https://api.openai.com/v1",
                 api_key_env: str = "OPENAI_API_KEY", temperature: float = 0.1,
                 max_tokens: int = 1024, timeout: float = 90.0, **_ignored):
        key = os.getenv(api_key_env)
        if not key:
            raise RuntimeError(f"Переменная окружения {api_key_env} не задана")
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"), timeout=timeout,
            headers={"Authorization": f"Bearer {key}"},
        )

    @property
    def name(self) -> str:
        return f"openai_compat/{self._model}"

    def complete(self, prompt: str, *, json_schema: Optional[dict] = None,
                 temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> str:
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": self._max_tokens if max_tokens is None else max_tokens,
        }
        if json_schema:
            payload["response_format"] = {"type": "json_schema", "json_schema": json_schema}
        r = self._client.post("/chat/completions", json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
