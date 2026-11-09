"""Локальный эмбеддер (sentence-transformers) — реализация IEmbedder."""
from __future__ import annotations

from app.core.interfaces import IEmbedder
from app.core.registry import register


@register("embed", "sentence_transformers")
class SentenceTransformersEmbedder(IEmbedder):
    def __init__(self, model: str = "cointegrated/rubert-tiny2", device: str = "auto"):
        from sentence_transformers import SentenceTransformer  # ленивый импорт: тяжёлая либа
        if device == "auto":
            try:
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"
            except ImportError:
                device = "cpu"
        self._m = SentenceTransformer(model, device=device)
        self._model_name = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._m.encode(texts, normalize_embeddings=True).tolist()
