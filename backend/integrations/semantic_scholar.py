from __future__ import annotations

import asyncio
import logging
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)


class _MinimumIntervalRateLimiter:
    """Ensures a minimum delay between outbound requests."""

    def __init__(self, min_interval_seconds: float) -> None:
        self._min_interval_seconds = max(min_interval_seconds, 0.0)
        self._last_call_started_at = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self._min_interval_seconds <= 0:
            return

        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call_started_at
            sleep_for = self._min_interval_seconds - elapsed
            if sleep_for > 0:
                await asyncio.sleep(sleep_for)
            self._last_call_started_at = time.monotonic()


class SemanticScholarClient:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        min_interval_seconds: float = 1.1,
        max_retries: int = 3,
        backoff_seconds: float = 1.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.max_retries = max(max_retries, 0)
        self.backoff_seconds = max(backoff_seconds, 0.1)

        headers: dict[str, str] = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        self._client = httpx.AsyncClient(timeout=20.0, headers=headers)
        self._rate_limiter = _MinimumIntervalRateLimiter(
            min_interval_seconds=min_interval_seconds
        )

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

        response = await self._get_with_retries(
            "/paper/search",
            params=params,
        )
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

        response = await self._get_with_retries(
            f"/paper/{quote(paper_id, safe='')}",
            params={"fields": fields},
        )
        return response.json()

    async def _get_with_retries(
        self,
        path: str,
        *,
        params: dict[str, str | int],
    ) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            await self._rate_limiter.acquire()
            response = await self._client.get(f"{self.base_url}{path}", params=params)

            if response.status_code != 429:
                response.raise_for_status()
                return response

            if attempt >= self.max_retries:
                response.raise_for_status()

            wait_seconds = self._retry_wait_seconds(response, attempt)
            logger.warning(
                "Semantic Scholar rate limited (429) on %s; retry %d/%d in %.2fs",
                path,
                attempt + 1,
                self.max_retries,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)

        raise RuntimeError(
            "Unexpected retry flow in SemanticScholarClient._get_with_retries"
        )

    def _retry_wait_seconds(self, response: httpx.Response, attempt: int) -> float:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return max(float(retry_after), 0.5)
            except ValueError:
                try:
                    retry_dt = parsedate_to_datetime(retry_after)
                    now = time.time()
                    return max(retry_dt.timestamp() - now, 0.5)
                except Exception:
                    pass
        return self.backoff_seconds * (2**attempt)

    async def aclose(self) -> None:
        await self._client.aclose()
