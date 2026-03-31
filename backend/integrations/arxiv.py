from __future__ import annotations

import asyncio
import logging
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx


ATOM_NAMESPACE = {"atom": "http://www.w3.org/2005/Atom"}
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


class ArxivClient:
    def __init__(
        self,
        *,
        api_url: str,
        min_interval_seconds: float = 1.1,
        max_retries: int = 3,
        backoff_seconds: float = 1.5,
    ) -> None:
        self.api_url = api_url
        self.max_retries = max(max_retries, 0)
        self.backoff_seconds = max(backoff_seconds, 0.1)
        self._client = httpx.AsyncClient(timeout=20.0)
        self._rate_limiter = _MinimumIntervalRateLimiter(
            min_interval_seconds=min_interval_seconds
        )

    async def resolve_metadata(self, arxiv_id: str) -> dict | None:
        response = await self._get_with_retries(params={"id_list": arxiv_id})

        root = ET.fromstring(response.text)
        entry = root.find("atom:entry", ATOM_NAMESPACE)
        if entry is None:
            return None

        title = self._get_text(entry, "atom:title")
        summary = self._get_text(entry, "atom:summary")
        published = self._get_text(entry, "atom:published")
        authors = [
            {"name": author_name.text.strip()}
            for author_name in entry.findall("atom:author/atom:name", ATOM_NAMESPACE)
            if author_name.text
        ]

        year = None
        if published:
            year = int(published[:4])

        return {
            "arxiv_id": arxiv_id,
            "title": title,
            "abstract": summary,
            "authors": authors,
            "year": year,
        }

    async def _get_with_retries(
        self,
        *,
        params: dict[str, str],
    ) -> httpx.Response:
        for attempt in range(self.max_retries + 1):
            await self._rate_limiter.acquire()
            response = await self._client.get(self.api_url, params=params)

            if response.status_code != 429:
                response.raise_for_status()
                return response

            if attempt >= self.max_retries:
                response.raise_for_status()

            wait_seconds = self._retry_wait_seconds(response, attempt)
            logger.warning(
                "arXiv rate limited (429) for params=%s; retry %d/%d in %.2fs",
                params,
                attempt + 1,
                self.max_retries,
                wait_seconds,
            )
            await asyncio.sleep(wait_seconds)

        raise RuntimeError("Unexpected retry flow in ArxivClient._get_with_retries")

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

    @staticmethod
    def _get_text(entry: ET.Element, path: str) -> str | None:
        node = entry.find(path, ATOM_NAMESPACE)
        if node is None or node.text is None:
            return None
        return " ".join(node.text.split())
