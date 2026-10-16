#!/usr/bin/env python3
"""Why a shown run is similar to the target: computed for the few results
shown, never for the corpus.

Per signal, the overlap (Jaccard) of the target's and the run's filed
tokens (:mod:`vmn_exp.core.similar_doc`), left out when either side has none
— for ``text`` the share of the target's words (FTS5 stems) the run holds;
the reasons are those of the :data:`REASONS` heaviest overlaps (weight x
overlap). Reasons read candidate first (``lr 3e-4 vs 1e-4`` = the run's lr
vs the target's).
"""
import math

from vmn_exp.core import similar_fts
from vmn_exp.core.similar_doc import CLEAN, STRUCTURED
from vmn_exp.core.similar_match import stems, words
from vmn_exp.core.similar_weights import SIGNAL_OF, SIGNALS
from vmn_exp.core.values import metric_number

REASONS = 3
LISTED = 3


def _listed(names):
    names = list(names)
    return ", ".join(names[:LISTED]) + (", …" if len(names) > LISTED else "")


def _counted(names, noun):
    return f"{len(names)} shared {noun}{'' if len(names) == 1 else 's'}: {_listed(names)}"


def fmt(value):
    """A param value as a reason shows it: ``3e-4``, ``0.25``, ``adam``."""
    plain = isinstance(value, (int, float)) and not isinstance(value, bool)
    try:
        number = metric_number(value) if plain else None
    except OverflowError:
        number = None
    if number is None or not math.isfinite(number) or (
            isinstance(value, int) and abs(value) > 2 ** 63):
        text = str(value)
        return text if len(text) <= 24 else text[:23] + "…"
    if number and (abs(number) < 1e-3 or abs(number) >= 1e6):
        mantissa, exponent = f"{number:.2e}".split("e")
        return f"{mantissa.rstrip('0').rstrip('.')}e{int(exponent)}"
    return f"{number:.4g}"


def _values(shared, prefix):
    return sorted(t[len(prefix):] for t in shared if t.startswith(prefix))


def _code(shared, *_):
    for prefix, text in (("commit:", "same base commit"), ("base:", "same base version"),
                         ("line:", "same version line")):
        found = _values(shared, prefix)
        if found:
            return f"{text} {found[0]}"
    return None


def _files(shared, *_):
    if CLEAN in shared:
        return "both clean trees"
    return _counted(_values(shared, "file:"), "file") if shared else None


def _symbols(shared, *_):
    names = [s.rsplit("/", 1)[-1] for s in _values(shared, "sym:")]
    return _counted(names, "function") if names else None


def _inputs(shared, row, _):
    digests = set(_values(shared, "input:"))
    inputs = row.get("inputs") if isinstance(row.get("inputs"), dict) else {}
    named = sorted((name, v.get("kind")) for name, v in inputs.items()
                   if isinstance(name, str) and isinstance(v, dict)
                   and str(v.get("digest")) in digests)
    if len(named) == 1:
        return f"same {'model' if named[0][1] == 'model' else 'dataset'} {named[0][0]}"
    if named:
        return "same inputs: " + _listed(name for name, _ in named)
    datasets = _values(shared, "ds:")
    return f"same dataset {datasets[0]}" if datasets else None


def _params(shared, row, target_row):
    keys = _values(shared, "pkey:")
    if not keys:
        return None
    mine, theirs = target_row.get("params") or {}, row.get("params") or {}
    same = set(_values(shared, "pval:"))
    differ = [k for k in keys if not any(v.startswith(k + "=") for v in same)]
    if differ:
        return ", ".join(f"{k} {fmt(theirs.get(k))} vs {fmt(mine.get(k))}" for k in differ[:2])
    return "same params: " + _listed(keys)


def _entry(shared, *_):
    sub = _values(shared, "sub:")
    if sub:
        return "same command " + sub[0]
    script = _values(shared, "cmd:")
    return f"same script {script[0]}" if script else None


def _objective(shared, *_):
    names = _values(shared, "metric:")
    return "same metrics: " + _listed(names) if names else None


def _branch(shared, *_):
    names = _values(shared, "branch:")
    return f"same branch {names[0]}" if names else None


_REASON_OF = {"code": _code, "files": _files, "symbols": _symbols, "inputs": _inputs,
              "params": _params, "entry": _entry, "objective": _objective, "branch": _branch}


def _jaccard(a, b):
    return len(a & b) / len(a | b) if a and b else None


class Explainer:
    """Reasons and signals of results against one target *doc* under signal
    *weights* (``{signal: weight}``; *text_only* explains the text alone).
    *match* (:class:`~vmn_exp.core.similar_match.Match`) lends its stems and
    document frequencies: shared words are named rarest first."""

    def __init__(self, conn, doc, weights, text_only=False, match=None):
        self._conn, self._doc, self._weights, self._text_only = conn, doc, weights, text_only
        self._stems = dict(match.stems if match is not None else stems(conn, words(doc.text)))
        self._mine = {s: w for w, ss in self._stems.items() for s in ss}
        self._df = match.df if match is not None else similar_fts.document_frequencies(
            conn, {"text": list(self._mine)})

    def prepare(self, docs):
        """Stem the words of *docs* and of every keyword phrase in one go."""
        texts = [d.text for d in docs] + [k for d in [self._doc, *docs] for k in d.keywords]
        self._stem([w for t in texts for w in words(t)])

    def _stem(self, found):
        missing = [w for w in dict.fromkeys(found) if w not in self._stems]
        self._stems.update(stems(self._conn, missing))
        self._stems.update((w, []) for w in missing if w not in self._stems)

    def _stems_of(self, text):
        found = words(text)
        self._stem(found)
        return {s for w in found for s in self._stems[w]}

    def explain(self, doc, row, target_row):
        """``(reasons, {signal: overlap})`` of the result *doc* (its *row*)."""
        found = {}
        if not self._text_only:
            for column in STRUCTURED:
                a, b = set(self._doc.cols.get(column, ())), set(doc.cols.get(column, ()))
                sim = _jaccard(a, b)
                if sim is not None:
                    found[SIGNAL_OF[column]] = (sim, _REASON_OF[column](
                        a & b, row, target_row or {}) if sim else None)
        text = self._text(doc)
        if text is not None:
            found["text"] = text
        ranked = sorted((s for s, (sim, why) in found.items()
                         if sim > 0 and why and self._weights.get(s, 0) > 0),
                        key=lambda s: (-self._weights[s] * found[s][0], SIGNALS.index(s)))
        return ([found[s][1] for s in ranked[:REASONS]],
                {s: round(sim, 4) for s, (sim, _) in found.items()})

    def _text(self, doc):
        theirs = self._stems_of(doc.text)
        if not self._mine or not theirs:
            return None
        shared = set(self._mine) & theirs
        sim = len(shared) / len(self._mine)  # how much of the target's text it holds
        if not sim:
            return 0.0, None
        named, covered = [], set()
        for phrase in dict.fromkeys(self._doc.keywords + doc.keywords):
            phrase_stems = self._stems_of(phrase)
            if phrase_stems and phrase_stems <= shared:
                named.append(phrase)
                covered |= phrase_stems
        rest = sorted(shared - covered, key=lambda s: (self._df.get(("text", s), 0), s))
        named += [self._mine[s] for s in rest][:max(0, REASONS - len(named))]
        return sim, "shared: " + ", ".join(named[:REASONS])
