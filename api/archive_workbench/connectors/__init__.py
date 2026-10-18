"""Open-library connectors. One search method each."""
from .base import Hit, SourceResult, search_libraries
from .dpla import Dpla
from .europeana import Europeana
from .gallica import Gallica
from .internet_archive import InternetArchive
from .loc import LibraryOfCongress
from .openalex import OpenAlex
from .wikidata import Wikidata

CONNECTORS = {
    "internet_archive": InternetArchive(),
    "loc": LibraryOfCongress(),
    "wikidata": Wikidata(),
    "openalex": OpenAlex(),
    "gallica": Gallica(),
    "europeana": Europeana(),
    "dpla": Dpla(),
}

DEFAULT_SOURCES = ["internet_archive", "loc", "wikidata", "openalex", "gallica"]

__all__ = ["CONNECTORS", "DEFAULT_SOURCES", "Hit", "SourceResult", "search_libraries"]
