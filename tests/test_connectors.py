import httpx

from archive_workbench.connectors.dpla import Dpla
from archive_workbench.connectors.europeana import Europeana
from archive_workbench.connectors.internet_archive import InternetArchive
from archive_workbench.connectors.loc import LibraryOfCongress
from archive_workbench.connectors.openalex import OpenAlex
from archive_workbench.connectors.wikidata import Wikidata
from archive_workbench.config import settings


class _Resp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_keys_are_required_for_europeana_and_dpla(monkeypatch):
    monkeypatch.setattr(settings, "europeana_api_key", "")
    monkeypatch.setattr(settings, "dpla_api_key", "")
    assert Europeana().configured() is False
    assert Dpla().configured() is False
    monkeypatch.setattr(settings, "europeana_api_key", "x")
    assert Europeana().configured() is True


def test_internet_archive_parses_docs(monkeypatch):
    def fake_get(url, **kwargs):
        assert "archive.org" in url
        return _Resp({"response": {"docs": [{
            "identifier": "kittur-1862",
            "title": "Kittur papers",
            "creator": ["Elphinstone"],
            "year": "1862",
            "description": "A minute.",
        }]}})
    monkeypatch.setattr(httpx, "get", fake_get)
    hits = InternetArchive().search("Kittur", 5)
    assert hits[0].url == "https://archive.org/details/kittur-1862"
    assert hits[0].creators == ["Elphinstone"]


def test_loc_wikidata_and_openalex(monkeypatch):
    def fake_get(url, **kwargs):
        if "loc.gov" in url:
            return _Resp({"results": [{
                "title": "Dharwar map",
                "url": "https://www.loc.gov/item/abc",
                "date": "1850",
                "contributor": ["Survey"],
                "description": ["A map"],
            }]})
        if "wikidata.org" in url:
            return _Resp({"search": [{
                "id": "Q123",
                "label": "Kittur",
                "description": "town",
                "concepturi": "https://www.wikidata.org/wiki/Q123",
            }]})
        return _Resp({"results": [{
            "display_name": "The Kittur rising",
            "id": "https://openalex.org/W1",
            "publication_year": 2011,
            "authorships": [{"author": {"display_name": "A. Rao"}}],
            "abstract_inverted_index": {"Kittur": [0], "rose": [1]},
        }]})
    monkeypatch.setattr(httpx, "get", fake_get)
    assert LibraryOfCongress().search("x")[0].title == "Dharwar map"
    assert Wikidata().search("x")[0].url.endswith("Q123")
    work = OpenAlex().search("x")[0]
    assert work.creators == ["A. Rao"] and "Kittur rose" in work.description
