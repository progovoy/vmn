"""A run's intent: what a human, or their AI, says the experiment is for.

``build_intent_entry`` makes the ``intent`` log entry every writer appends
(``vmn-exp create|run|add --intent/--intent-file``, ``start_run(intent=)``,
``run.set_intent``); the fold keeps the latest one. ``parse_intent_file``
splits a file's optional YAML front matter (``keywords``, ``generator``) off
its text. Pure: no IO, no clock (writers add the timestamp).
"""
from __future__ import annotations

import yaml

MAX_TEXT_BYTES = 16384
MAX_KEYWORDS = 50
_FENCE = "---"
_FRONT_MATTER_ENDS = ("---", "...")


def build_intent_entry(text, keywords=None, generator=None) -> dict:
    """The ``intent`` entry: *text* stripped and cut to ``MAX_TEXT_BYTES`` of
    UTF-8 (``truncated: True`` then), *keywords* (a list, or a comma-separated
    string) stripped and deduplicated case-insensitively, the first spelling
    kept, at most ``MAX_KEYWORDS``. ValueError on an empty or non-string text."""
    text = text.strip() if isinstance(text, str) else ""
    if not text:
        raise ValueError("An intent needs a non-empty text")
    text, truncated = _capped_text(text)
    entry = {"type": "intent", "text": text}
    kept = _keywords(keywords)
    if kept:
        entry["keywords"] = kept
    generator = "" if generator is None else str(generator).strip()
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
            keywords = meta.get("keywords")
            if isinstance(keywords, str):
                keywords = _comma_list(keywords)
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


def _capped_text(text):
    encoded = text.encode("utf-8")
    if len(encoded) <= MAX_TEXT_BYTES:
        return text, False
    # A cut UTF-8 prefix is invalid only in its last, partial character.
    return encoded[:MAX_TEXT_BYTES].decode("utf-8", "ignore"), True


def _keywords(keywords):
    if keywords is None:
        return []
    if isinstance(keywords, str):
        keywords = _comma_list(keywords)
    kept, seen = [], set()
    for keyword in keywords:
        word = _keyword_text(keyword)
        if word and word.casefold() not in seen:
            seen.add(word.casefold())
            kept.append(word)
    return kept[:MAX_KEYWORDS]


def _keyword_text(keyword):
    if isinstance(keyword, bool) or not isinstance(keyword, (str, int, float)):
        raise ValueError(f"Intent keywords must be strings, got {keyword!r}")
    return str(keyword).strip()


def _comma_list(text):
    return [part.strip() for part in text.split(",") if part.strip()]
