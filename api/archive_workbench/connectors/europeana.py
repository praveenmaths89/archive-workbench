"""Europeana search. Requires EUROPEANA_API_KEY."""
from __future__ import annotations

import httpx

from ..config import settings
from .base import Hit, UA, as_list, first_text


class Europeana:
    name = "europeana"
    bucket = "europeana"
    per_minute = 30

    def configured(self) -> bool:
        return bool(settings.europeana_api_key)

    def search(self, query: str, limit: int = 8) -> list[Hit]:
        response = httpx.get(
            "https://api.europeana.eu/record/v2/search.json",
            params={"wskey": settings.europeana_api_key, "query": query, "rows": str(limit)},
            headers={"User-Agent": UA},
            timeout=20,
        )
        response.raise_for_status()
        hits = []
        for item in response.json().get("items") or []:
            guid = item.get("guid") or ""
            if guid.startswith("http://"):
                guid = "https://" + guid[len("http://"):]
            hits.append(Hit(
                source=self.name,
                title=first_text(item.get("title")) or "Untitled",
                url=guid or "https://www.europeana.eu/",
                creators=as_list(item.get("dcCreator")),
                date=first_text(item.get("year") or item.get("timestamp")) or None,
                description=first_text(item.get("dcDescription")),
            ))
        return hits
