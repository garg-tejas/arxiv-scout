from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx


ATOM_NAMESPACE = {"atom": "http://www.w3.org/2005/Atom"}


class ArxivClient:
    def __init__(self, *, api_url: str) -> None:
        self.api_url = api_url

    async def resolve_metadata(self, arxiv_id: str) -> dict | None:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(self.api_url, params={"id_list": arxiv_id})
            response.raise_for_status()

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

    @staticmethod
    def _get_text(entry: ET.Element, path: str) -> str | None:
        node = entry.find(path, ATOM_NAMESPACE)
        if node is None or node.text is None:
            return None
        return " ".join(node.text.split())
