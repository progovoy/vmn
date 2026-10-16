#!/usr/bin/env python3
"""A run's similar-runs document: what the FTS table files of it (plan 24).

One column per signal. ``text`` is the run's text document
(:func:`~vmn_exp.core.similar_profile.document_text`), tokenized by FTS5
itself. Every other column holds *structured tokens* — ``file:src/a.py``,
``sym:src/a.py::f``, ``pkey:lr``, ``commit:abcdef1``, … (:func:`structured`)
— each filed as one opaque word (:func:`word`: ``t`` + 12 digits of its
sha1), which the ``unicode61`` tokenizer keeps whole, so identical structure
matches exactly. The raw tokens are kept beside the FTS row (:meth:`Doc.data`)
for the reasons of the few results shown. Pure: no storage.
"""
import hashlib
import json
import math

from vmn_exp.core.similar_profile import build_profile

# Bump when what a run files changes: runs filed by another version are refiled.
PROFILE_VERSION = "1"
COLUMNS = ("text", "code", "files", "symbols", "inputs", "params", "entry", "objective",
           "branch")
STRUCTURED = COLUMNS[1:]
CLEAN = "clean:"
# Tokens kept for reasons only, never filed for matching: nearly every run of
# an app shares its base version, which would make every run a match.
UNMATCHED = ("base:", "line:")


def _utf8(text):
    """*text* with ``?`` for each lone surrogate (only a hand-written log holds
    one): SQLite stores UTF-8."""
    return text.encode("utf-8", "replace").decode("utf-8")


def word(token):
    """The FTS word a structured *token* is filed as: ``t`` and 12 digits of
    its sha1 — decimal ones, so the porter stemmer leaves it whole (it trims
    the letter suffixes of a hex word)."""
    digest = int(hashlib.sha1(token.encode("utf-8", "replace")).hexdigest(), 16)
    return "t%012d" % (digest % 10 ** 12)


def _scalar(value):
    """A param value as the text of its ``pval:`` token; None for no scalar."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return None if value is None else json.dumps(value)
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except OverflowError:
            return str(value)
        return repr(number) if math.isfinite(number) else None
    return None


def _code(p):
    tokens = []
    if p.commit:
        tokens.append("commit:" + p.commit)
    if p.base:
        tokens.append("base:" + p.base)
        core = p.base.split("-", 1)[0].split("+", 1)[0].split(".")
        if len(core) >= 2 and all(part.isdigit() for part in core[:2]):
            tokens.append(f"line:{core[0]}.{core[1]}")
    return tokens


def _changes(p, prefix, values):
    return ([CLEAN] if p.clean else []) + [prefix + v for v in values]


def _params(p):
    tokens = ["pkey:" + k for k in p.params]
    for key, value in p.params.items():
        text = _scalar(value)
        if text is not None:
            tokens.append(f"pval:{key}={text}")
    return tokens


def _entry(p):
    if not p.script:
        return []
    tokens = ["cmd:" + p.script]
    if p.args and not p.args[0].startswith("-"):
        tokens.append(f"sub:{p.script} {p.args[0]}")
    tokens.append(" ".join(("args:" + p.script,) + tuple(p.args)))
    return tokens


def structured(p):
    """``{column: sorted raw tokens}`` of a profile's structured columns."""
    found = {
        "code": _code(p),
        "files": _changes(p, "file:", p.files),
        "symbols": _changes(p, "sym:", p.symbols),
        "inputs": [t for i in p.inputs
                   for t in ("ds:" + i.dataset, "input:" + i.digest if i.digest else None) if t],
        "params": _params(p),
        "entry": _entry(p),
        "objective": ["metric:" + m for m in p.objective],
        "branch": ["branch:" + p.branch] if p.branch else [],
    }
    return {column: tuple(sorted(set(found[column]))) for column in STRUCTURED}


class Doc:
    """A run's (or a target's) document: *cols* ``{column: raw tokens}``
    (``text`` excluded), its *text*, its intent *keywords* and *rerun* key."""

    __slots__ = ("verstr", "rerun", "cols", "text", "keywords", "has_intent")

    def __init__(self, verstr, rerun, cols, text, keywords=(), has_intent=False):
        self.verstr, self.rerun, self.cols = verstr, rerun, cols
        self.text, self.keywords, self.has_intent = _utf8(text or ""), tuple(keywords), has_intent

    def fts_values(self):
        """The FTS row's column values, in :data:`COLUMNS` order."""
        return [self.text] + [" ".join(word(t) for t in self.cols[c]
                                       if not t.startswith(UNMATCHED)) for c in STRUCTURED]

    def data(self):
        """What :meth:`from_data` reads back (the text lives in the FTS row)."""
        return {"cols": {c: list(v) for c, v in self.cols.items() if v},
                "keywords": list(self.keywords)}

    @classmethod
    def from_data(cls, verstr, rerun, data, text=""):
        cols = data.get("cols") or {}
        return cls(verstr, rerun, {c: tuple(cols.get(c) or ()) for c in STRUCTURED}, text,
                   data.get("keywords") or ())


def build_doc(row, features=None, intent=None, hypothesis=None, *, command=None,
              create_note=None, text=None):
    """The :class:`Doc` of one run, or of a target (*row* may lack a verstr;
    *text* replaces the text document, a ``--context`` query)."""
    p = build_profile(row, features, intent, hypothesis, command=command,
                      create_note=create_note, text=text)
    verstr = row.get("verstr") if isinstance(row, dict) else None
    return Doc(verstr, p.rerun, structured(p), p.text, p.keywords, p.has_intent)
