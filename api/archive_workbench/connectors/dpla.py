"""Digital Public Library of America. Requires DPLA_API_KEY."""
from __future__ import annotations

import httpx

from ..config import settings
from .base import Hit, UA, as_list, first_text


class Dpla:
    name = "dpla"
    bucket = "dpla"
    per_minute = 30

    def configured(self) -> bool:
        return bool(settings.dpla_api_key)

    def search(self, query: str, limit: int = 8) -> list[Hit]:
        response = httpx.get(
            "https://api.dp.la/v2/items",
            params={"api_key": settings.dpla_api_key, "q": query, "page_size": str(limit)},
            headers={"User-Agent": UA},
            timeout=20,
        )
        response.raise_for_status()
        hits = []
        for doc in response.json().get("docs") or []:
            source = doc.get("sourceResource") or {}
            hits.append(Hit(
                source=self.name,
                title=first_text(source.get("title")) or "Untitled",
                url=(doc.get("isShownAt") or "https://dp.la/"),
                creators=as_list(source.get("creator")),
                date=first_text(source.get("date")) or None,
                description=first_text(source.get("description")),
            ))
        return hits
