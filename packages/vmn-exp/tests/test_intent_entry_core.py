"""The ``intent`` log entry builder and the ``--intent-file`` parser.

``build_intent_entry`` makes the entry every writer appends (CLI ``--intent``/
``--intent-file``, SDK ``start_run(intent=)``/``run.set_intent``): the text
capped at 16 KiB of UTF-8, keywords stripped, deduplicated and capped at 50.
``parse_intent_file`` splits an optional YAML front matter (``keywords``,
``generator``) off a file's text.
"""
import pytest
from vmn_exp.core.fold import fold_intent, fold_log
from vmn_exp.core.intent import (
    MAX_KEYWORDS,
    MAX_TEXT_BYTES,
    build_intent_entry,
    parse_intent_file,
)

# -- build_intent_entry ---------------------------------------------------------


def test_the_entry_is_a_user_intent_with_the_text():
    assert build_intent_entry("focal loss for the long tail") == {
        "type": "intent", "text": "focal loss for the long tail", "source": "user"}


def test_keywords_and_generator_are_kept():
    entry = build_intent_entry("x", keywords=["focal loss", "gamma"],
                               generator="claude-opus-5-5")
    assert entry["keywords"] == ["focal loss", "gamma"]
    assert entry["generator"] == "claude-opus-5-5"


def test_the_text_is_stripped():
    assert build_intent_entry("\n  hypothesis: gamma=2 helps\n\n")["text"] == (
        "hypothesis: gamma=2 helps")


@pytest.mark.parametrize("text", ["", "   \n\t "])
def test_an_empty_text_is_refused(text):
    with pytest.raises(ValueError, match="intent"):
        build_intent_entry(text)


@pytest.mark.parametrize("text", [None, 3, ["a"]])
def test_a_non_string_text_is_refused(text):
    with pytest.raises(ValueError, match="intent"):
        build_intent_entry(text)


def test_a_text_within_the_cap_is_not_marked_truncated():
    entry = build_intent_entry("a" * MAX_TEXT_BYTES)
    assert len(entry["text"]) == MAX_TEXT_BYTES
    assert "truncated" not in entry


def test_a_long_text_is_cut_to_the_cap_and_marked_truncated():
    assert MAX_TEXT_BYTES == 16384
    entry = build_intent_entry("a" * (MAX_TEXT_BYTES + 10))
    assert entry["text"] == "a" * MAX_TEXT_BYTES
    assert entry["truncated"] is True


def test_the_cut_never_splits_a_multibyte_character():
    # 3-byte characters: the cap falls inside the 5462nd one.
    entry = build_intent_entry("€" * 6000)
    encoded = entry["text"].encode("utf-8")
    assert len(encoded) <= MAX_TEXT_BYTES
    assert entry["text"] == "€" * (MAX_TEXT_BYTES // 3)
    assert entry["truncated"] is True


def test_keywords_are_stripped_and_empty_ones_dropped():
    entry = build_intent_entry("x", keywords=["  focal loss ", "", "  ", "gamma"])
    assert entry["keywords"] == ["focal loss", "gamma"]


def test_keywords_are_deduplicated_case_insensitively_keeping_the_first_spelling():
    entry = build_intent_entry("x", keywords=["Focal Loss", "focal loss", "GAMMA", "gamma"])
    assert entry["keywords"] == ["Focal Loss", "GAMMA"]


def test_keywords_are_capped():
    assert MAX_KEYWORDS == 50
    entry = build_intent_entry("x", keywords=[f"k{i}" for i in range(80)])
    assert entry["keywords"] == [f"k{i}" for i in range(MAX_KEYWORDS)]


def test_a_comma_separated_keyword_string_is_split():
    entry = build_intent_entry("x", keywords="focal loss, class imbalance,,gamma")
    assert entry["keywords"] == ["focal loss", "class imbalance", "gamma"]


def test_number_keywords_become_strings():
    assert build_intent_entry("x", keywords=[2019, 0.5])["keywords"] == ["2019", "0.5"]


@pytest.mark.parametrize("keyword", [{"a": 1}, ["nested"], True])
def test_other_keyword_types_are_refused(keyword):
    with pytest.raises(ValueError, match="keyword"):
        build_intent_entry("x", keywords=["ok", keyword])


def test_no_keywords_and_no_generator_leave_the_keys_out():
    entry = build_intent_entry("x", keywords=["", " "], generator="  ")
    assert "keywords" not in entry
    assert "generator" not in entry


def test_the_generator_is_stripped():
    assert build_intent_entry("x", generator=" gpt-x \n")["generator"] == "gpt-x"


def test_the_entry_folds_as_the_runs_intent():
    entry = dict(build_intent_entry("why", keywords=["k"]), timestamp="2026-01-01T00:00:00Z")
    assert fold_intent(fold_log([entry])) == {"text": "why", "keywords": ["k"],
                                              "source": "user"}


# -- parse_intent_file ----------------------------------------------------------


def test_a_file_without_front_matter_is_all_text():
    assert parse_intent_file("Hypothesis: x\n\nmore\n") == ("Hypothesis: x\n\nmore\n", None, None)


def test_front_matter_keywords_list_and_generator():
    content = "---\nkeywords: [focal loss, gamma]\ngenerator: claude-opus-5-5\n---\nThe text.\n"
    assert parse_intent_file(content) == ("The text.\n", ["focal loss", "gamma"],
                                          "claude-opus-5-5")


def test_front_matter_block_list_keywords():
    content = "---\nkeywords:\n  - focal loss\n  - long tail\n---\nbody"
    assert parse_intent_file(content) == ("body", ["focal loss", "long tail"], None)


def test_front_matter_comma_string_keywords():
    content = "---\nkeywords: focal loss, long tail\n---\nbody"
    assert parse_intent_file(content)[1] == ["focal loss", "long tail"]


def test_front_matter_closed_by_dots():
    assert parse_intent_file("---\ngenerator: g\n...\nbody") == ("body", None, "g")


def test_empty_front_matter():
    assert parse_intent_file("---\n---\nbody") == ("body", None, None)


def test_unknown_front_matter_keys_are_ignored():
    assert parse_intent_file("---\ntitle: t\n---\nbody") == ("body", None, None)


def test_crlf_and_a_byte_order_mark():
    content = "\ufeff---\r\nkeywords: [a]\r\n---\r\nbody\r\n"
    assert parse_intent_file(content) == ("body\r\n", ["a"], None)


def test_an_unclosed_front_matter_is_text():
    content = "---\nnot closed\n"
    assert parse_intent_file(content) == (content, None, None)


def test_a_dash_rule_later_in_the_text_is_not_front_matter():
    content = "intro\n---\nkeywords: [a]\n---\n"
    assert parse_intent_file(content) == (content, None, None)


def test_invalid_front_matter_yaml_is_refused():
    with pytest.raises(ValueError, match="front matter"):
        parse_intent_file("---\nkeywords: [unclosed\n---\nbody")


def test_front_matter_that_is_not_a_mapping_is_refused():
    with pytest.raises(ValueError, match="front matter"):
        parse_intent_file("---\n- a\n- b\n---\nbody")


def test_a_parsed_file_builds_an_entry():
    text, keywords, generator = parse_intent_file(
        "---\nkeywords: [Gamma, gamma]\ngenerator: g\n---\n\nFocal loss.\n")
    assert build_intent_entry(text, keywords, generator) == {
        "type": "intent", "text": "Focal loss.", "keywords": ["Gamma"],
        "generator": "g", "source": "user"}
