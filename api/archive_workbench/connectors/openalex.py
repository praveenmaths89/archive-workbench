"""OpenAlex works search. No key. A descriptive User-Agent is required by their polite pool."""
from __future__ import annotations

import httpx

from .base import Hit, UA


class OpenAlex:
    name = "openalex"
    bucket = "openalex"
    per_minute = 30

    def configured(self) -> bool:
        return True

    def search(self, query: str, limit: int = 8) -> list[Hit]:
        response = httpx.get(
            "https://api.openalex.org/works",
            params={"search": query, "per-page": str(limit)},
            headers={"User-Agent": UA},
            timeout=20,
        )
        response.raise_for_status()
        hits = []
        for work in response.json().get("results", []):
            authors = []
            for authorship in work.get("authorships") or []:
                name = (authorship.get("author") or {}).get("display_name")
                if name:
                    authors.append(name)
            abstract = ""
            inverted = work.get("abstract_inverted_index") or {}
            if inverted:
                positions: list[tuple[int, str]] = []
                for word, spots in inverted.items():
                    for spot in spots:
                        positions.append((spot, word))
                positions.sort()
                abstract = " ".join(word for _, word in positions)[:600]
            hits.append(Hit(
                source=self.name,
                title=work.get("display_name") or work.get("id") or "Untitled",
                url=work.get("id") or "",
                creators=authors,
                date=str(work.get("publication_year")) if work.get("publication_year") else None,
                description=abstract,
            ))
        return hits
