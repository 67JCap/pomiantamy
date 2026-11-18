"""Единый HTTP-клиент проекта — вся работа с интернетом проходит здесь.

Retry+backoff, прокси из конфига, ротация User-Agent, вежливые задержки.
Инкапсуляция в одном месте = смена прокси/агента без правок источников.
"""
from __future__ import annotations

import asyncio
import random
from typing import Optional

import httpx

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 Safari/17.4",
]


class HttpClient:
    def __init__(self, proxy: Optional[str] = None, timeout: float = 20.0,
                 retries: int = 3, politeness_delay: float = 2.0):
        self._retries = retries
        self._delay = politeness_delay
        self._client = httpx.AsyncClient(
            timeout=timeout,
            proxy=proxy,
            follow_redirects=True,
            headers={"User-Agent": random.choice(USER_AGENTS)},
        )

    async def get(self, url: str, **kw) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(self._retries):
            try:
                await asyncio.sleep(random.uniform(0.3, self._delay))  # politeness
                r = await self._client.get(url, **kw)
                if r.status_code < 500 or r.status_code == 404:
                    return r
                last_exc = httpx.HTTPStatusError("5xx", request=r.request, response=r)
            except httpx.HTTPError as e:
                last_exc = e
            await asyncio.sleep(2 ** attempt + random.random())  # backoff
        assert last_exc
        raise last_exc

    async def download(self, url: str, path: str) -> bool:
        """Скачать бинарник (картинка/видео). True при успехе."""
        try:
            async with self._client.stream("GET", url) as r:
                if r.status_code != 200:
                    return False
                with open(path, "wb") as f:
                    async for chunk in r.aiter_bytes(64 * 1024):
                        f.write(chunk)
            return True
        except httpx.HTTPError:
            return False

    async def aclose(self):
        await self._client.aclose()
