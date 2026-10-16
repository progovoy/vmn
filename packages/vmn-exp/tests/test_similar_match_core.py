"""The FTS5 side of a similar-runs query (vmn_exp.core.similar_match): the
MATCH a target asks — rarest terms first, quoted, bounded — its bm25 ranking
under column weights, and the deadline interrupting it."""
import sqlite3

import pytest
from similar_fixtures import changed, run
from vmn_exp.core import similar_fts, similar_match
from vmn_exp.core.similar_doc import COLUMNS, build_doc


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:", isolation_level=None)
    similar_fts.ensure_tables(c)
    return c


def _file(conn, *docs):
    similar_fts.file_docs(conn, "app", [(d.verstr, d) for d in docs])


def _text(verstr, text):
    row = run(verstr, note=text) if verstr else {"note": text}
    return build_doc(row, None)


def _ranked(conn, target, columns=COLUMNS, weights=None):
    match = similar_match.build_match(conn, target, columns)
    expression = match.expression()
    if expression is None:
        return []
    weights = weights or dict.fromkeys(COLUMNS, 1.0)
    return [v for v, _ in similar_match.rank(conn, "app", expression, weights, 0, 50)[0]]


def test_words_are_lowercased_and_distinct():
    assert similar_match.words("Focal LOSS, focal_loss!") == ["focal", "loss"]
    assert similar_match.words(None) == []


def test_text_words_are_stemmed_by_fts5(conn):
    assert similar_match.stems(conn, ["smoothing", "resnet"]) == {
        "smoothing": ["smooth"], "resnet": ["resnet"]}


def test_a_stemmed_word_matches_its_other_forms(conn):
    _file(conn, _text("a", "label smoothing"), _text("b", "focal loss"))
    assert _ranked(conn, _text(None, "smoothed labels")) == ["a"]


def test_the_rarer_shared_term_ranks_higher(conn):
    _file(conn, *[_text(f"common{i}", "loss") for i in range(6)],
          _text("rare", "loss gamma"))
    assert _ranked(conn, _text(None, "gamma loss"))[0] == "rare"


def test_query_syntax_in_a_text_is_quoted_never_parsed(conn):
    _file(conn, _text("a", "near star colon quote"))
    for text in ('"', "*", "NEAR(a b)", "text: x", 'a" OR "b', "AND OR NOT", "^col"):
        _ranked(conn, _text(None, text))  # never a syntax error
    assert _ranked(conn, _text(None, 'NEAR "star*" colon:')) == ["a"]


def test_terms_no_document_holds_are_left_out(conn):
    _file(conn, _text("a", "focal"))
    match = similar_match.build_match(conn, _text(None, "unheard"), COLUMNS)
    assert match.expression() is None


def test_each_column_asks_its_rarest_terms_first_and_at_most_max(conn, monkeypatch):
    monkeypatch.setattr(similar_match, "MAX_TERMS", 2)
    _file(conn, _text("a", "one two three"), _text("b", "one two"), _text("c", "one"))
    match = similar_match.build_match(conn, _text(None, "one two three"), COLUMNS)
    assert [t[1] for t in match.terms] == ["three", "two"]


def test_past_the_rarest_terms_common_ones_stop_at_the_postings_budget(conn, monkeypatch):
    monkeypatch.setattr(similar_match, "MIN_TERMS", 1)
    monkeypatch.setattr(similar_match, "POSTINGS_BUDGET", 3)
    monkeypatch.setattr(similar_match, "POSTINGS_PER_DOC", 1)
    _file(conn, _text("a", "rare common"), _text("b", "common"), _text("c", "common"))
    match = similar_match.build_match(conn, _text(None, "rare common"), COLUMNS)
    assert [t[1] for t in match.terms] == ["rare"]


def test_the_postings_budget_grows_with_the_documents_filed(conn, monkeypatch):
    monkeypatch.setattr(similar_match, "MIN_TERMS", 1)
    monkeypatch.setattr(similar_match, "POSTINGS_BUDGET", 3)
    monkeypatch.setattr(similar_match, "POSTINGS_PER_DOC", 2)
    _file(conn, _text("a", "rare common"), _text("b", "common"), _text("c", "common"))
    match = similar_match.build_match(conn, _text(None, "rare common"), COLUMNS)
    assert [t[1] for t in match.terms] == ["rare", "common"]


def test_structured_tokens_match_in_their_own_column_only(conn):
    file_doc = build_doc(run("f"), changed(["x.py"]))
    _file(conn, file_doc, _text("t", "x py"))
    target = build_doc({}, changed(["x.py"]))
    assert _ranked(conn, target) == ["f"]


def test_column_weights_order_the_ranking(conn):
    target = build_doc({"note": "focal"}, changed(["x.py"]))
    _file(conn, build_doc(run("files"), changed(["x.py"])), _text("text", "focal"),
          *[_text(f"o{i}", "other") for i in range(4)])
    heavy_files = dict(dict.fromkeys(COLUMNS, 1.0), files=50.0)
    heavy_text = dict(dict.fromkeys(COLUMNS, 1.0), text=50.0)
    assert _ranked(conn, target, weights=heavy_files)[0] == "files"
    assert _ranked(conn, target, weights=heavy_text)[0] == "text"


def test_unasked_columns_are_left_out_of_the_match(conn):
    _file(conn, build_doc(run("f", note="zzz"), changed(["x.py"])))
    target = build_doc({"note": "other"}, changed(["x.py"]))
    assert similar_match.build_match(conn, target, ("text",)).expression() is None


def test_a_passed_deadline_interrupts_the_query(conn):
    _file(conn, *[_text(f"r{i}", "focal loss") for i in range(50)])
    with pytest.raises(similar_match.SimilarDeadlineExceeded):
        with similar_match.deadline(conn, similar_match._clock() - 1):
            _ranked(conn, _text(None, "focal"))
    assert _ranked(conn, _text(None, "focal"))  # the handler is gone again
