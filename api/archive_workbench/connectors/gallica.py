"""Gallica SRU. No key. A failure here does not hide other sources."""
from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from .base import Hit, UA

NS = {
    "srw": "http://www.loc.gov/zing/srw/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


class Gallica:
    name = "gallica"
    bucket = "gallica"
    per_minute = 30

    def configured(self) -> bool:
        return True

    def search(self, query: str, limit: int = 8) -> list[Hit]:
        safe = query.replace('"', " ")
        response = httpx.get(
            "https://gallica.bnf.fr/SRU",
            params={
                "version": "1.2",
                "operation": "searchRetrieve",
                "query": f'gallica all "{safe}"',
                "maximumRecords": str(limit),
            },
            headers={"User-Agent": UA},
            timeout=20,
        )
        response.raise_for_status()
        root = ET.fromstring(response.text)
        hits = []
        for record in root.findall(".//srw:recordData", NS):
            title = _text(record, "dc:title")
            url = _text(record, "dc:identifier")
            if not title:
                continue
            if url and not url.startswith("http"):
                url = ""
            hits.append(Hit(
                source=self.name,
                title=title,
                url=url or "https://gallica.bnf.fr/",
                creators=[c for c in _all(record, "dc:creator")],
                date=_text(record, "dc:date") or None,
                description=_text(record, "dc:description"),
            ))
        return hits


def _text(node, path: str) -> str:
    found = node.find(path, NS)
    return (found.text or "").strip() if found is not None and found.text else ""


def _all(node, path: str) -> list[str]:
    return [(el.text or "").strip() for el in node.findall(path, NS) if el.text]
