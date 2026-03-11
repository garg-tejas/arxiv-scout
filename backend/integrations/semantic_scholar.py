from __future__ import annotations

import httpx
from urllib.parse import quote


class SemanticScholarClient:
    def __init__(self, *, base_url: str, api_key: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

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
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{self.base_url}/paper/search",
                params=params,
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()
        return payload.get("data", [])

    async def get_paper_context(self, paper_id: str) -> dict:
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key

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

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(
                f"{self.base_url}/paper/{quote(paper_id, safe='')}",
                params={"fields": fields},
                headers=headers,
            )
            response.raise_for_status()
            return response.json()
