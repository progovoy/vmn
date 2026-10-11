"""An intent is UTF-8 through and through: a lone surrogate (JSON with a cut
emoji, a stdin read with ``surrogateescape``) is refused in its keywords and
its generator as in its text, so no stored intent can break a JSON answer."""
import pytest
from vmn_exp.core.intent import build_intent_entry, parse_intent_file

CUT_EMOJI = "focal \ud83d"


@pytest.mark.parametrize("kwargs", [
    {"text": CUT_EMOJI},
    {"text": "focal loss", "keywords": ["ok", CUT_EMOJI]},
    {"text": "focal loss", "keywords": CUT_EMOJI + ", ok"},
    {"text": "focal loss", "generator": "model \udc80"},
], ids=["text", "keyword", "keyword-string", "generator"])
def test_a_lone_surrogate_is_refused_with_a_message_naming_it(kwargs):
    with pytest.raises(ValueError, match="UTF-8") as caught:
        build_intent_entry(**kwargs)
    message = str(caught.value)
    message.encode("utf-8")  # the message itself prints anywhere
    assert "\\ud83d" in message or "\\udc80" in message


def test_a_front_matter_surrogate_keyword_is_refused():
    # A YAML escape: the file is valid UTF-8, the keyword it parses to is not.
    text, keywords, generator = parse_intent_file('---\nkeywords: ["focal \\ud83d"]\n---\nbody')
    assert keywords == [CUT_EMOJI]
    with pytest.raises(ValueError, match="keyword"):
        build_intent_entry(text, keywords, generator)


def test_a_full_emoji_is_kept():
    entry = build_intent_entry("focal \U0001f525", keywords=["\U0001f525 loss"], generator="mé")
    assert (entry["text"], entry["keywords"], entry["generator"]) == (
        "focal \U0001f525", ["\U0001f525 loss"], "mé")
