"""Hand-built rows and a duck-typed snapshot for the similar-runs core tests.

The similar modules read a snapshot through ``.rows``, ``.features_of``,
``.intent_of``, ``.hypothesis_of`` and ``.declared_schema()`` (plus the
optional ``run_states``/``create_notes`` maps), so a few dicts stand in for an
index snapshot here.
"""


def run(verstr, *, commit="aaaaaaa", base="1.0.0", code=None, **fields):
    """A lean leaderboard row; its code is unique to *verstr* unless *code* is given."""
    row = {
        "verstr": verstr,
        "code_verstr": code or f"{base}-dev.{commit}.c{verstr.replace('.', '')}",
        "base_version": base,
        "timestamp": "2026-01-01T00:00:00Z",
        "name": None,
        "note": None,
        "branch": None,
        "tags": {},
        "params": {},
        "metrics": {},
        "inputs": {},
        "parent": None,
        "imported_from": None,
    }
    row.update(fields)
    return row


def changed(files=(), symbols=(), commits=(), **extra):
    """A ``features`` value with the given changed files/symbols and commit subjects."""
    features = {"changed": {"files": list(files), "symbols": list(symbols)}}
    if commits:
        features["commits"] = list(commits)
    features.update(extra)
    return features


def dataset(name, digest, kind="dataset"):
    return {name: {"uri": f"vmn-registry://{name}", "digest": digest, "kind": kind}}


class FakeSnapshot:
    def __init__(self, rows, features=None, intents=None, hypotheses=None,
                 declared=None, run_states=None, create_notes=None):
        self.rows = tuple(rows)
        self._features = features or {}
        self._intents = intents or {}
        self._hypotheses = hypotheses or {}
        self._declared = declared or {}
        self.run_states = run_states or {}
        self.create_notes = create_notes or {}

    def features_of(self, verstr):
        return self._features.get(verstr)

    def intent_of(self, verstr):
        return self._intents.get(verstr)

    def hypothesis_of(self, verstr):
        return self._hypotheses.get(verstr)

    def declared_schema(self):
        return self._declared


def verstrs(items):
    return [item["verstr"] for item in items]
