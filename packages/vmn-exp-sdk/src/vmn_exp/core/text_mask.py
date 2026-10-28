#!/usr/bin/env python3
"""Text with its per-run detail masked, so texts that differ only there
compare equal: uuids, versions, paths, hex ids and numbers (sizes, steps,
counts). "CUDA out of memory. Tried to allocate 2.31 GiB" and "... 1.07 GiB"
mask the same. Failure signatures (``ui/failure_signature.py``) and note
signatures (:mod:`vmn_exp.core.note_sigs`) are built on it.

Pure: no storage, no clock.
"""
import functools
import re

MAX_MASKED = 160
_MASKS = [
    (re.compile(r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b", re.IGNORECASE), "<uuid>"),
    (re.compile(r"\b\d+\.\d+\.\d+(?:\.\d+)?(?:-[\w.]+)?(?:\+[\w.]+)?"), "<ver>"),
    (re.compile(r"(?<![\w.<>])(?:~|\.{1,2})?(?:/[\w.\-+@%=]+)+/?"), "<path>"),
    (re.compile(r"\b[A-Za-z]:\\[\w\\.\-]+"), "<path>"),
    (re.compile(r"\b0x[0-9a-f]+\b", re.IGNORECASE), "<hex>"),
    (re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,}\b", re.IGNORECASE), "<hex>"),
    (re.compile(r"\d+(?:\.\d+)?(?:[eE][-+]?\d+)?"), "<n>"),
]


@functools.lru_cache(maxsize=4096)
def mask(text):
    """*text* with per-run detail masked and whitespace collapsed, at most
    :data:`MAX_MASKED` characters."""
    for pattern, placeholder in _MASKS:
        text = pattern.sub(placeholder, text)
    return " ".join(text.split())[:MAX_MASKED]
