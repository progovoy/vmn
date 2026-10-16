"""Plan 24 F5: :func:`vmn_exp.core.query_extra.snapshot_extra` — what a query
reads of an index snapshot beyond its lean rows: ``outputs``, ancestry,
``intent``/``keywords`` (its ``intent_of`` side table) and ``similar()``
(FTS5 over the runs' text documents).

``similar("<text>")`` holds for a run whose text document (intent text and
keywords, note, hypothesis, commit subjects) holds every word of the text,
stemmed (``porter unicode61``) — an AND of the words, never a ranking."""
import pytest
from vmn_exp.core import similar_fts
from vmn_exp.core.fold import fold_log
from vmn_exp.core.index import snapshot_of_folds
from vmn_exp.core.query import QueryError, filter_rows
from vmn_exp.core.query_extra import SNAPSHOT_FIELDS, bind_similar_scope, snapshot_extra
from vmn_exp.core.similar_corpus import snapshot_scope

APP = "trainer"


def _run(idx, verstr, intent=None, note=None, parent=None, losses=()):
    log = [{"timestamp": "t0", "type": "create", "params": {}, "note": None}]
    log += [{"timestamp": "t1", "type": "metrics", "values": {"loss": v}} for v in losses]
    if intent:
        log.append({"timestamp": "t1", "type": "intent", "source": "user", **intent})
    meta = {"verstr": verstr, "timestamp": f"2026-01-0{idx}T00:00:00Z", "code_verstr": verstr,
            "base_version": "0.0.1", "note": note, "parent": parent}
    return idx, meta, fold_log(log)


@pytest.fixture
def snap():
    return snapshot_of_folds(APP, [
        _run(1, "a", {"text": "Try focal loss", "keywords": ["class imbalance"]}),
        _run(2, "b", {"text": "focal only"}),
        _run(3, "c", {"text": "focal losses, on the long tail"}, parent="a"),
        _run(4, "d", note="baseline focal loss rerun"),
        _run(5, "e", losses=(1.0, 0.5)),
    ])


def _verstrs(snap, text, extra=None):
    rows = list(snap.rows)
    return [r["verstr"] for r in filter_rows(rows, text, extra=extra or snapshot_extra(snap))]


def test_the_snapshot_fields_are_what_lean_rows_lack(snap):
    assert {"outputs", "ancestors", "intent", "keywords", "similar"} == SNAPSHOT_FIELDS
    assert not SNAPSHOT_FIELDS & set(snap.rows[0])
    assert set(snapshot_extra(snap)) == SNAPSHOT_FIELDS
    assert snapshot_extra(None) is None


def test_intent_and_keywords_come_from_the_intent_side_table(snap):
    assert _verstrs(snap, 'intent ~ "focal"') == ["a", "b", "c"]
    assert _verstrs(snap, 'keywords ~ "IMBALANCE"') == ["a"]
    assert _verstrs(snap, "intent = null") == ["d", "e"]
    assert _verstrs(snap, 'under("a") and intent ~ "tail"') == ["c"]


def test_similar_needs_every_word_stemmed_in_the_text_document(snap):
    assert _verstrs(snap, 'similar("focal loss")') == ["a", "c", "d"]
    assert _verstrs(snap, 'similar("FOCAL")') == ["a", "b", "c", "d"]
    assert _verstrs(snap, 'similar("imbalance")') == ["a"]  # keywords are text
    assert _verstrs(snap, 'similar("focal unheard")') == []
    assert _verstrs(snap, 'similar("focal loss") and not under("a")') == ["a", "d"]


def test_query_syntax_in_the_text_is_only_words(snap):
    assert _verstrs(snap, "similar('focal\" OR NEAR(loss) *')") == []  # "or", "near" needed
    assert _verstrs(snap, "similar('\"focal\": loss^ *')") == ["a", "c", "d"]
    assert _verstrs(snap, "similar('NOT focal')") == []  # "not" is a word to find


def test_similar_without_fts5_is_a_query_error(snap, monkeypatch):
    monkeypatch.setattr(similar_fts, "_FTS5", [False])
    with pytest.raises(QueryError, match="FTS5"):
        _verstrs(snap, 'similar("focal")')


def test_a_bound_scope_is_searched_instead_of_a_memory_one(snap):
    other = snapshot_of_folds(APP, [_run(1, "b", {"text": "loss"})])
    asked = []

    def scope_of(snapshot):
        asked.append(snapshot)
        return snapshot_scope(APP, other)

    bind_similar_scope(snap, scope_of)
    assert _verstrs(snap, 'similar("loss")') == ["b"]
    assert asked == [snap]


def test_a_summarized_view_finds_its_base_snapshots_scope(snap):
    found = []
    bind_similar_scope(snap, lambda s: found.append(s) or snapshot_scope(APP, s))
    view = snap.summarized({"loss": {"summary": "max"}})
    assert view is not snap
    _verstrs(view, 'similar("loss")')
    assert found == [view]
