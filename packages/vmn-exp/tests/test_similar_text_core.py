"""The ``text`` signal of similar runs (vmn_exp.core.similar_text): tokens, a
run's text document and BM25 over it."""
from collections import Counter

import pytest
from similar_fixtures import run
from vmn_exp.core.similar_text import (
    KEYWORD_REPEAT,
    Bm25,
    document_terms,
    query_weights,
    shared_reason,
    tokenize,
)


def test_tokens_are_lowercased_and_split_on_camel_case_snake_case_and_punctuation():
    assert tokenize("FocalLoss for class_imbalance, HTTPServer/resnet50") == [
        "focalloss", "focal", "loss", "class", "imbalance", "httpserver", "http", "server",
        "resnet50",
    ]


def test_stopwords_and_single_characters_are_dropped():
    assert tokenize("The loss of a model is in the data, x = 2") == ["loss", "model", "data"]


def test_tokenize_of_nothing_is_empty():
    assert tokenize("") == []
    assert tokenize(None) == []


def test_a_run_document_holds_intent_name_note_tags_commits_and_hypothesis():
    row = run("a", name="focal sweep", note="baseline recall",
              tags={"owner": "alice", "smoke": ""})
    terms = document_terms(
        row,
        features={"commits": ["wire trainer"]},
        intent={"text": "minority classes", "keywords": []},
        hypothesis="gamma helps",
    )
    assert set(terms) == {
        "focal", "sweep", "baseline", "recall", "owner", "alice", "smoke",
        "wire", "trainer", "minority", "classes", "gamma", "helps",
    }


def test_intent_keywords_count_three_times():
    terms = Counter(document_terms(run("a"), intent={"text": "", "keywords": ["label smoothing"]}))
    assert KEYWORD_REPEAT == 3
    assert terms == {"label": 3, "smoothing": 3}


def test_the_create_note_stands_in_for_a_missing_note():
    assert document_terms(run("a"), create_note="quick probe") == ["quick", "probe"]
    assert document_terms(run("a", note="kept"), create_note="probe") == ["kept"]


def test_malformed_feature_and_intent_values_are_ignored():
    terms = document_terms(run("a", tags=None), features={"commits": "nope"},
                           intent={"text": 7, "keywords": "x"}, hypothesis=3)
    assert terms == []


def _bm25(docs):
    df = Counter(term for doc in docs for term in set(doc))
    return Bm25(len(docs), sum(map(len, docs)) / len(docs), df.get)


def test_bm25_prefers_a_document_with_the_rarer_term():
    docs = [["focal", "loss"], ["loss", "loss"], ["loss", "adam"]]
    bm25 = _bm25(docs)
    weights = query_weights(["focal", "loss"])
    focal, common = (bm25.score(weights, Counter(d), len(d)) for d in docs[:2])
    assert focal > common > 0
    assert bm25.idf("focal") > bm25.idf("loss")


def test_bm25_is_zero_without_a_shared_term():
    bm25 = _bm25([["focal"], ["adam"]])
    assert bm25.score(query_weights(["sgd"]), Counter(["adam"]), 1) == 0.0


def test_bm25_favours_the_shorter_of_two_documents_with_the_same_term_count():
    docs = [["focal", "a1"], ["focal", "b1", "b2", "b3", "b4", "b5"], ["c1"]]
    bm25 = _bm25(docs)
    weights = query_weights(["focal"])
    short, long_ = (bm25.score(weights, Counter(d), len(d)) for d in docs[:2])
    assert short > long_


def test_repeated_query_terms_weigh_more_but_saturate():
    weights = query_weights(["focal", "focal", "focal", "loss"])
    assert weights["focal"] > weights["loss"] == pytest.approx(1.0)
    assert weights["focal"] < 3


def test_the_text_reason_names_shared_keyword_phrases_before_rare_terms():
    docs = [["label", "smoothing", "focal", "loss"], ["loss"], ["loss", "smoothing"]]
    bm25 = _bm25(docs)
    reason = shared_reason(
        Counter(["label", "smoothing", "focal", "loss", "extra"]), Counter(docs[0]),
        bm25.idf, phrases=["Label Smoothing"],
    )
    assert reason == "shared: label smoothing, focal, loss"


def test_no_text_reason_without_a_shared_term():
    assert shared_reason(Counter(["a1"]), Counter(["b1"]), lambda t: 1.0) is None


@pytest.mark.parametrize("text, tokens", [
    ("NaN", ["nan"]),
    ("nan", ["nan"]),
    ("ResNet", ["resnet", "res", "net"]),
    ("resnet", ["resnet"]),
    ("PyTorch", ["pytorch", "py", "torch"]),
    ("pytorch", ["pytorch"]),
    ("GPUs", ["gpus"]),
    ("gpus", ["gpus"]),
    ("LayerNorm", ["layernorm", "layer", "norm"]),
    ("layernorm", ["layernorm"]),
    ("BFloat16", ["bfloat16"]),
    ("HTTPServer", ["httpserver", "http", "server"]),
    ("getUserName", ["getusername", "get", "user", "name"]),
    ("focal loss", ["focal", "loss"]),
])
def test_a_word_keeps_its_whole_lowercased_form_and_adds_its_camel_case_parts(text, tokens):
    assert tokenize(text) == tokens


def test_camel_case_parts_drop_stopwords_and_one_character_tokens_but_the_whole_stays():
    assert tokenize("isTrain") == ["istrain", "train"]
    assert tokenize("x") == []


@pytest.mark.parametrize("query, document", [
    ("nan", "Expect NaN loss"),
    ("NaN", "expect nan loss"),
    ("resnet", "ResNet-18 baseline"),
    ("ResNet", "resnet baseline"),
    ("pytorch", "PyTorch port"),
    ("gpus", "8 GPUs"),
])
def test_a_word_matches_whatever_its_capitalisation(query, document):
    assert query.lower() in tokenize(document)


def test_the_text_reason_names_a_camel_case_word_once():
    terms = Counter(tokenize("ResNet NaN"))
    reason = shared_reason(terms, terms, lambda t: 1.0)
    assert reason == "shared: nan, resnet"
