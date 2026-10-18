"""Library of Congress JSON search. Capped at 20 requests a minute."""
from __future__ import annotations

import httpx

from .base import Hit, UA, as_list, first_text


class LibraryOfCongress:
    name = "loc"
    bucket = "loc"
    per_minute = 20

    def configured(self) -> bool:
        return True

    def search(self, query: str, limit: int = 8) -> list[Hit]:
        last_error: Exception | None = None
        response = None
        for _ in range(2):
            try:
                response = httpx.get(
                    "https://www.loc.gov/search/",
                    params={"q": query, "fo": "json", "c": str(min(limit, 25))},
                    headers={"User-Agent": UA, "Accept": "application/json"},
                    timeout=httpx.Timeout(45.0, connect=10.0),
                )
                response.raise_for_status()
                last_error = None
                break
            except httpx.TimeoutException as exc:
                last_error = exc
        if last_error is not None or response is None:
            raise last_error or RuntimeError("Library of Congress did not respond")
        payload = response.json()
        rows = payload.get("results") or payload.get("content", {}).get("results") or []
        hits = []
        for row in rows[:limit]:
            title = first_text(row.get("title"))
            url = row.get("url") or ""
            if url and url.startswith("/"):
                url = "https://www.loc.gov" + url
            if not title or not url:
                continue
            date = row.get("date") or (row.get("item") or {}).get("date")
            hits.append(Hit(
                source=self.name,
                title=title,
                url=url,
                creators=as_list(row.get("contributor")),
                date=first_text(date) or None,
                description=first_text(row.get("description")),
            ))
        return hits
