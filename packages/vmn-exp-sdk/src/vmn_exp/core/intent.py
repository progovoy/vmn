"""A run's intent: what a human, or their AI, says the experiment is for.

``build_intent_entry`` makes the ``intent`` log entry every writer appends
(``vmn-exp create|run|add --intent/--intent-file``, ``start_run(intent=)``,
``run.set_intent``); the fold keeps the latest one. ``parse_intent_file``
splits a file's optional YAML front matter (``keywords``, ``generator``) off
its text. Pure: no IO, no clock (writers add the timestamp).
"""
from __future__ import annotations

import datetime

import yaml

MAX_TEXT_BYTES = 16384
MAX_KEYWORDS = 50
# The most of a refused value an error message shows.
MAX_ERROR_REPR = 200
# What a keyword or the generator may be: text, or a number or date YAML parsed.
_SCALARS = (str, int, float, datetime.date)
_FENCE = "---"
_FRONT_MATTER_ENDS = ("---", "...")


def build_intent_entry(text, keywords=None, generator=None) -> dict:
    """The ``intent`` entry: *text* stripped and cut to ``MAX_TEXT_BYTES`` of
    UTF-8 (``truncated: True`` then), *keywords* (a list or tuple, or a
    comma-separated string) stripped and deduplicated case-insensitively, the
    first spelling kept, at most ``MAX_KEYWORDS``; numbers and dates among
    them, and a number or date *generator*, become text. ValueError on an
    empty or non-string text, on keywords or a generator of any other type,
    and on a lone surrogate (no UTF-8) in any of them."""
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        raise ValueError("An intent needs a non-empty text")
    text, truncated = cap_utf8(_utf8(text, "The intent text"), MAX_TEXT_BYTES)
    entry = {"type": "intent", "text": text}
    kept = clean_keywords(keywords)
    if kept:
        entry["keywords"] = kept
    if generator is not None:
        generator = _utf8(_scalar_text(generator, "The intent generator must be a string"),
                          "The intent generator")
    if generator:
        entry["generator"] = generator
    entry["source"] = "user"
    if truncated:
        entry["truncated"] = True
    return entry


def parse_intent_file(content):
    """``(text, keywords, generator)`` of an intent file's *content*: a
    leading ``---`` ... ``---`` (or ``...``) YAML block is its front matter,
    the rest its text; without one it is all text. ValueError when the front
    matter is not a YAML mapping."""
    content = content.lstrip("\ufeff")
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].strip() != _FENCE:
        return content, None, None
    for end, line in enumerate(lines[1:], 1):
        if line.strip() in _FRONT_MATTER_ENDS:
            meta = _front_matter("".join(lines[1:end]))
            keywords = _split_if_text(meta.get("keywords"))
            return "".join(lines[end + 1:]), keywords, meta.get("generator")
    return content, None, None


def _front_matter(block):
    try:
        meta = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid intent front matter: {exc}") from None
    if meta is None:
        return {}
    if not isinstance(meta, dict):
        raise ValueError("Invalid intent front matter: expected a YAML mapping")
    return meta


def cap_utf8(text, max_bytes):
    """``(text, cut)``: *text* cut to *max_bytes* bytes of UTF-8, never
    mid-character; *cut* whether it was."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text, False
    # A cut UTF-8 prefix is invalid only in its last, partial character.
    return encoded[:max_bytes].decode("utf-8", "ignore"), True


def clean_keywords(keywords):
    """*keywords* as an intent entry keeps them (see :func:`build_intent_entry`):
    a list of strings, ``[]`` for None; ValueError on any other type."""
    if keywords is None:
        return []
    keywords = _split_if_text(keywords)
    if not isinstance(keywords, (list, tuple)):
        raise ValueError("Intent keywords must be a list or a comma-separated "
                         f"string, got {_short_repr(keywords)}")
    kept, seen = [], set()
    for keyword in keywords:
        word = _utf8(_scalar_text(keyword, "Intent keywords must be strings"), "An intent keyword")
        if word and word.casefold() not in seen:
            seen.add(word.casefold())
            kept.append(word)
    return kept[:MAX_KEYWORDS]


def _scalar_text(value, what):
    """*value* (see :data:`_SCALARS`) as stripped text; else ValueError(*what*)."""
    if isinstance(value, bool) or not isinstance(value, _SCALARS):
        raise ValueError(f"{what}, got {_short_repr(value)}")
    return str(value).strip()


def _utf8(text, what):
    """*text*, when it is UTF-8; ValueError naming *what* on a lone
    surrogate (a cut emoji in JSON, stdin read with ``surrogateescape``)."""
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError(f"{what} is not valid UTF-8 (a lone surrogate): "
                         f"{_short_repr(text)}") from None
    return text


def _split_if_text(keywords):
    """A comma-separated keyword string as its list; anything else as is."""
    if not isinstance(keywords, str):
        return keywords
    return [part.strip() for part in keywords.split(",") if part.strip()]


def _short_repr(value):
    shown = repr(value)
    return shown if len(shown) <= MAX_ERROR_REPR else shown[:MAX_ERROR_REPR - 3] + "..."
