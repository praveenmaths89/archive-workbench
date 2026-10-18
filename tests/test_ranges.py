from archive_workbench.ranges import parse_pages
import pytest


def test_all_and_empty():
    assert parse_pages(None, 5) is None
    assert parse_pages("", 5) is None
    assert parse_pages("all", 5) is None


def test_ranges_and_open_ends():
    assert parse_pages("1-3, 5", 6) == [1, 2, 3, 5]
    assert parse_pages("4-", 6) == [4, 5, 6]
    assert parse_pages("-2", 6) == [1, 2]


def test_rejects_garbage_and_backwards():
    with pytest.raises(ValueError):
        parse_pages("page three", 4)
    with pytest.raises(ValueError):
        parse_pages("5-2", 8)
    with pytest.raises(ValueError):
        parse_pages("9", 4)
