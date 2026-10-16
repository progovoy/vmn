""":func:`vmn_exp.core.similar_search.search` over several ready scopes (what
``vmn-exp ui`` searches, each labelled by its workspace and app), and items
without their features (the UI's payload has none)."""
from similar_fixtures import FakeSnapshot, changed, run
from vmn_exp.core.similar_corpus import snapshot_scope
from vmn_exp.core.similar_items import item_payload
from vmn_exp.core.similar_search import search

SYMS = ["train.py::train_step"]
TARGET = {"row": None, "features": changed(["train.py"], SYMS)}


def _scope(label, *verstrs):
    rows = [run(v) for v in verstrs]
    snap = FakeSnapshot(rows, features={v: changed(["train.py"], SYMS) for v in verstrs})
    scope = snapshot_scope("app", snap)
    scope.label = label
    return scope


def test_a_search_ranks_over_every_scope_it_is_given():
    scopes = [_scope(("ws1", "app"), "a"), _scope(("ws2", "app"), "b")]
    found = search(None, None, scopes, TARGET, with_features=False)
    # Labels come back as lists: an item is JSON-shaped (utf8_safe).
    assert sorted((item["app"], item["verstr"]) for item in found) == [
        (["ws1", "app"], "a"), (["ws2", "app"], "b")]
    assert not any("features" in item for item in found)


def test_an_item_without_features_leaves_them_out():
    scope = _scope("app", "a")
    [found] = search(None, None, [scope], TARGET)
    assert "features" in found
    item = {"verstr": "a", "row": scope.rows.snapshot.rows[0], "app": "app", "score": 1.0,
            "reasons": [], "signals": {}, "group_size": 1}
    assert "features" not in item_payload(item, scope.rows, with_features=False)
