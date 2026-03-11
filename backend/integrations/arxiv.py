from __future__ import annotations


class ArxivClient:
    async def resolve_metadata(self, arxiv_id: str) -> dict:
        raise NotImplementedError("arXiv resolution is implemented in checkpoint 1.3.")
