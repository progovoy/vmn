"""Intent values beyond plain strings: a YAML date keyword is text like a
number, a generator that is not a scalar (a list, a mapping, bytes) is
refused, and the value an error names is cut so the message stays short."""
import datetime

import pytest
from vmn_exp.core.intent import build_intent_entry, parse_intent_file

MAX_REPR = 200


def test_date_and_datetime_keywords_become_strings():
    keywords = [datetime.date(2024, 1, 1), datetime.datetime(2024, 1, 2, 3, 4, 5)]
    assert build_intent_entry("x", keywords=keywords)["keywords"] == [
        "2024-01-01", "2024-01-02 03:04:05"]


def test_a_front_matter_date_keyword_is_kept_as_text():
    text, keywords, generator = parse_intent_file("---\nkeywords: [2024-01-01, lr]\n---\nbody")
    assert build_intent_entry(text, keywords, generator)["keywords"] == ["2024-01-01", "lr"]


@pytest.mark.parametrize("generator", [["a", "b"], {"model": "x"}, b"model", True],
                         ids=["list", "mapping", "bytes", "bool"])
def test_a_generator_that_is_not_a_scalar_is_refused(generator):
    with pytest.raises(ValueError, match="generator"):
        build_intent_entry("x", generator=generator)


def test_a_front_matter_list_generator_is_refused():
    text, keywords, generator = parse_intent_file("---\ngenerator: [a, b]\n---\nbody")
    with pytest.raises(ValueError, match="generator"):
        build_intent_entry(text, keywords, generator)


@pytest.mark.parametrize("generator, stored", [(4, "4"), (0.5, "0.5"),
                                               (datetime.date(2024, 1, 1), "2024-01-01")])
def test_a_scalar_generator_is_stored_as_text(generator, stored):
    assert build_intent_entry("x", generator=generator)["generator"] == stored


def _message(**kwargs):
    with pytest.raises(ValueError) as caught:
        build_intent_entry("x", **kwargs)
    return str(caught.value)


@pytest.mark.parametrize("kwargs", [
    {"keywords": ["ok", {"k": "v" * 5000}]},
    {"keywords": {"k": "v" * 5000}},
    {"generator": ["g" * 5000]},
], ids=["keyword", "keywords", "generator"])
def test_an_error_names_the_bad_value_cut_short(kwargs):
    message = _message(**kwargs)
    prefix, _, shown = message.partition(", got ")
    assert prefix and shown
    assert len(shown) <= MAX_REPR
    assert shown.endswith("...")
