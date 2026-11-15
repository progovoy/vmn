"""ModelListing.response pages its name-ordered rows (plan 42 E11)."""
from types import SimpleNamespace

from vmn_exp.ui.readers.models import ModelListing


def _listing(*rows):
    return ModelListing({r["name"]: SimpleNamespace(row=r) for r in rows})


def _row(name, kind="model"):
    return {"name": name, "kind": kind}


def _names(response):
    return [r["name"] for r in response["models"]]


def test_response_offset_limit_and_total():
    listing = _listing(_row("d"), _row("a"), _row("c"), _row("b"))
    page = listing.response(offset=1, limit=2)
    assert _names(page) == ["b", "c"] and page["total"] == 4


def test_response_without_limit_is_unchanged():
    listing = ModelListing({"b": SimpleNamespace(row=_row("b")), "headerless": SimpleNamespace(row=None),
                            "a": SimpleNamespace(row=_row("a")), "c": SimpleNamespace(row=_row("c"))})
    assert listing.response() == {"models": [_row("a"), _row("b"), _row("c")]}


def test_total_counts_after_the_kind_filter():
    listing = _listing(_row("a"), _row("b", "dataset"), _row("c"), _row("d", "dataset"))
    page = listing.response("dataset", offset=0, limit=1)
    assert _names(page) == ["b"] and page["total"] == 2
