"""Wikidata entity search. No key."""
from __future__ import annotations

import httpx

from .base import Hit, UA


class Wikidata:
    name = "wikidata"
    bucket = "wikidata"
    per_minute = 30

    def configured(self) -> bool:
        return True

    def search(self, query: str, limit: int = 8) -> list[Hit]:
        response = httpx.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "search": query,
                "language": "en",
                "format": "json",
                "limit": str(limit),
            },
            headers={"User-Agent": UA},
            timeout=20,
        )
        response.raise_for_status()
        hits = []
        for row in response.json().get("search", []):
            qid = row.get("id")
            if not qid:
                continue
            hits.append(Hit(
                source=self.name,
                title=row.get("label") or qid,
                url=row.get("concepturi") or f"https://www.wikidata.org/wiki/{qid}",
                description=row.get("description") or "",
            ))
        return hits
