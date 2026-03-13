from __future__ import annotations

import httpx


class FirecrawlClient:
    def __init__(self, *, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        self._client = httpx.AsyncClient(timeout=30.0, headers=headers)

    async def fetch_paper(self, url: str) -> dict | None:
        if not self.api_key:
            return None

        payload = {
            "url": url,
            "formats": ["markdown"],
        }

        response = await self._client.post(
            f"{self.base_url}/v1/scrape",
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        if not data.get("success", True):
            return None
        return data.get("data") or data

    async def aclose(self) -> None:
        await self._client.aclose()
