"""Internet Archive advanced search. No key."""
from __future__ import annotations

import httpx

from .base import Hit, UA, as_list, first_text


class InternetArchive:
    name = "internet_archive"
    bucket = "internet_archive"
    per_minute = 30

    def configured(self) -> bool:
        return True

    def search(self, query: str, limit: int = 8) -> list[Hit]:
        params = [
            ("q", query),
            ("output", "json"),
            ("rows", str(limit)),
            ("fl[]", "identifier"),
            ("fl[]", "title"),
            ("fl[]", "creator"),
            ("fl[]", "year"),
            ("fl[]", "description"),
        ]
        response = httpx.get(
            "https://archive.org/advancedsearch.php",
            params=params, headers={"User-Agent": UA}, timeout=20,
        )
        response.raise_for_status()
        docs = response.json().get("response", {}).get("docs", [])
        hits = []
        for doc in docs:
            identifier = doc.get("identifier")
            if not identifier:
                continue
            hits.append(Hit(
                source=self.name,
                title=first_text(doc.get("title")) or identifier,
                url=f"https://archive.org/details/{identifier}",
                creators=as_list(doc.get("creator")),
                date=first_text(doc.get("year")) or None,
                description=first_text(doc.get("description")),
            ))
        return hits
