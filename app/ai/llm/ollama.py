"""Ollama LLM через OpenAI-compatible endpoint (/v1).

Локальный режим для RTX 3060: qwen2.5:7b-instruct и любые другие GGUF-модели.
Ключевое: этот же класс работает с LM Studio, vLLM, llama.cpp server —
это один интерфейс ILLM на все локальные серверы.
"""
from __future__ import annotations

import json
from typing import Optional

import httpx

from app.core.interfaces import ILLM
from app.core.registry import register


@register("llm", "ollama")
class OllamaLLM(ILLM):
    def __init__(self, model: str, base_url: str = "http://localhost:11434/v1",
                 temperature: float = 0.1, max_tokens: int = 1024,
                 timeout: float = 120.0, **_ignored):
        self._model = model
        self._base = base_url.rstrip("/")
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = httpx.Client(base_url=self._base, timeout=timeout)

    @property
    def name(self) -> str:
        return f"ollama/{self._model}"

    def complete(self, prompt: str, *, json_schema: Optional[dict] = None,
                 temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> str:
        payload = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": self._max_tokens if max_tokens is None else max_tokens,
        }
        if json_schema:  # structured output — модели обязаны выдавать валидный JSON
            payload["response_format"] = {"type": "json_schema", "json_schema": json_schema}
        r = self._client.post("/chat/completions", json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def ping(self) -> bool:
        try:
            self._client.get("/models").raise_for_status()
            return True
        except Exception:
            return False


# Утилита для всех LLM-бэкендов: безопасный парсинг JSON-ответа модели
def parse_json(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"В ответе модели нет JSON: {text[:200]}")
    return json.loads(text[start:end + 1])
