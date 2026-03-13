from __future__ import annotations

import asyncio
import time

import httpx
from urllib.parse import quote


class _SlidingWindowRateLimiter:
    """Simple sliding-window rate limiter: at most *max_calls* within *period* seconds."""

    def __init__(self, max_calls: int, period: float) -> None:
        self._max_calls = max_calls
        self._period = period
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                # Evict timestamps outside the window
                self._timestamps = [
                    t for t in self._timestamps if now - t < self._period
                ]
                if len(self._timestamps) < self._max_calls:
                    self._timestamps.append(now)
                    return
                # Calculate how long to sleep until the oldest entry expires
                sleep_for = self._period - (now - self._timestamps[0])
            await asyncio.sleep(max(sleep_for, 0.05))


class SemanticScholarClient:
    def __init__(self, *, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

        headers: dict[str, str] = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        self._client = httpx.AsyncClient(timeout=20.0, headers=headers)
        # ~15 requests per 60 s — conservative for the free tier (100 req / 5 min)
        self._rate_limiter = _SlidingWindowRateLimiter(max_calls=15, period=60.0)

    async def search(self, query: str, *, limit: int = 10) -> list[dict]:
        params = {
            "query": query,
            "limit": limit,
            "fields": ",".join(
                [
                    "paperId",
                    "title",
                    "abstract",
                    "year",
                    "citationCount",
                    "authors",
                    "externalIds",
                    "url",
                ]
            ),
        }

        await self._rate_limiter.acquire()
        response = await self._client.get(
            f"{self.base_url}/paper/search",
            params=params,
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("data", [])

    async def get_paper_context(self, paper_id: str) -> dict:
        fields = ",".join(
            [
                "paperId",
                "title",
                "year",
                "citationCount",
                "references.paperId",
                "references.title",
                "references.year",
                "references.citationCount",
                "citations.paperId",
                "citations.title",
                "citations.year",
                "citations.citationCount",
            ]
        )

        await self._rate_limiter.acquire()
        response = await self._client.get(
            f"{self.base_url}/paper/{quote(paper_id, safe='')}",
            params={"fields": fields},
        )
        response.raise_for_status()
        return response.json()

    async def aclose(self) -> None:
        await self._client.aclose()
