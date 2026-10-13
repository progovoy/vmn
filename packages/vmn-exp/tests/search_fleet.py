"""A :class:`~leaderboard_fleet.Fleet` whose runs carry the text the search
index covers (plan 23 S8): name, note, tags, params, author, intent, and in
their run states a command and, when failed, an error summary. Also a
brute-force reference of what each field holds and of the ⌘K ranking."""
import re

from leaderboard_fleet import Fleet
from vmn_exp.core.index_snapshot import IndexSnapshot

WORDS = ["alpha", "Beta", "GRID", "lr", "sweep", "baseline", "Ünïcode", "ΣIGMA", "x-1",
         "a b", "tune_7", "Ab"]


class TextFleet(Fleet):
    def __init__(self, seed=0, links=False):
        super().__init__(seed, links)
        self.intents = {}

    def _phrase(self, words=2):
        return " ".join(self.rng.choice(WORDS) for _ in range(words))

    def _text(self):
        rng = self.rng
        maybe = lambda value: value if rng.random() < 0.6 else None  # noqa: E731
        return {
            "name": maybe(f"{self.rng.choice(WORDS)}-t{rng.randrange(1000)}"),
            "note": maybe(self._phrase(3)),
            "tags": {rng.choice(WORDS): self._phrase(1) for _ in range(rng.randrange(3))},
            "extra": {"model": rng.choice(WORDS), "layers": rng.randrange(8),
                      "list": [rng.choice(WORDS), 3]},
            "author": maybe(f"{rng.choice(['alice', 'Bob'])}@example.com"),
            "command": ["python", "train.py", "--opt", self._phrase(1)],
        }

    def _fold(self, i):
        spec = self.specs[i]
        text = spec.setdefault("text", self._text())
        row = super()._fold(i)
        return dict(row, name=text["name"], note=text["note"], tags=dict(text["tags"]),
                    author=text["author"], params=dict(row["params"], **text["extra"]),
                    has_intent=spec["verstr"] in self.intents)

    def _with_text(self, i, state):
        if state is None:
            return None
        out = dict(state, command=list(self.specs[i]["text"]["command"]))
        if state.get("exit_code") not in (0, None):
            out["error_summary"] = f"RuntimeError: {self._phrase(2)}"
        return out

    def append(self, parent=None, state=None, verstr=None):
        verstr = super().append(parent, state, verstr)
        self.states[verstr] = self._with_text(len(self.specs) - 1, state)
        return verstr

    def set_state(self, i, state):
        super().set_state(i, self._with_text(i, state))

    def retext(self, i):
        self.specs[i]["text"] = self._text()
        self.rows[i] = self._fold(i)

    def set_intent(self, i, text):
        verstr = self.specs[i]["verstr"]
        if text is None:
            self.intents.pop(verstr, None)
        else:
            self.intents[verstr] = {"text": text}
        self.rows[i] = self._fold(i)

    def remove(self, i):
        self.intents.pop(self.specs[i]["verstr"], None)
        super().remove(i)

    def mutate_text(self, count):
        """*count* random text changes on top of :meth:`Fleet.mutate`'s."""
        rng = self.rng
        for _ in range(count):
            i = rng.randrange(len(self.specs))
            op = rng.choice(["retext", "intent", "unintent", "fail"])
            if op == "retext":
                self.retext(i)
            elif op == "intent":
                self.set_intent(i, self._phrase(4))
            elif op == "unintent":
                self.set_intent(i, None)
            else:
                self.set_state(i, {"state": "finished", "exit_code": 2})

    def snapshot(self):
        self.generation += 1
        return IndexSnapshot.build(
            "app", self.generation, list(self.rows), dict(self.states),
            observed_at=dict(self.observed), intents=dict(self.intents),
        )


# -- the brute-force reference ----------------------------------------------
def _strings(value):
    if value is None:
        return []
    if isinstance(value, dict):
        return [v for v in value.values() if isinstance(v, str)] + list(value)
    if isinstance(value, (list, tuple)):
        return [v for v in value if isinstance(v, str)]
    return [str(value)]


def field_texts(snapshot, row):
    """``{field: [strings]}`` the index should match *row* on."""
    state = snapshot.run_states.get(row["verstr"]) or {}
    intent = snapshot.intents.get(row["verstr"]) or {}
    params = row.get("params") or {}
    return {
        "name": _strings(row.get("name")),
        "verstr": [row["verstr"]],
        "note": _strings(row.get("note")),
        "tags": _strings(row.get("tags")),
        "params": [s for v in params.values() for s in _strings(v)],
        "command": _strings(state.get("command")),
        "branch": _strings(row.get("branch")),
        "author": _strings(row.get("author")),
        "error_summary": _strings(state.get("error_summary")),
        "intent": _strings(intent.get("text")),
    }


def hits(snapshot, needle, fields):
    """Storage slots with a string of one of *fields* containing *needle*."""
    needle = needle.lower()
    return [i for i, row in enumerate(snapshot.rows)
            if any(needle in s.lower() for f in fields for s in field_texts(snapshot, row)[f])]


def ranked(snapshot, text, limit, archived=False):
    """``[(slot, match)]``: ``@N``, then verstr prefix, name prefix, then any
    hit (first field in order), each newest first."""
    t = text.strip().lower()
    order = list(field_texts(snapshot, snapshot.rows[0]))
    found = []
    for i, row in enumerate(snapshot.rows):
        if row.get("archived") and not archived:
            continue
        texts = field_texts(snapshot, row)
        n = re.fullmatch(r"@?(\d+)", t)
        if n and row["idx"] == int(n.group(1)):
            found.append((0, -i, "idx"))
        elif row["verstr"].lower().startswith(t):
            found.append((1, -i, "verstr"))
        elif any(s.lower().startswith(t) for s in texts["name"]):
            found.append((2, -i, "name"))
        else:
            field = next((f for f in order if any(t in s.lower() for s in texts[f])), None)
            if field:
                found.append((3, -i, field))
    return [(-i, field) for _, i, field in sorted(found)[:limit]]
