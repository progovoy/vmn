"""A simulated experiment index for leaderboard tests: successive
IndexSnapshots that honour the index's identity contract (an unchanged
record keeps its row and run-state objects; a moved one is shallow-copied
with its new ``idx``), so a cache can derive a generation from the last."""
import datetime
import random

from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.log import experiment_row

APP = "app"
T0 = datetime.datetime(2026, 3, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def finished(code=0):
    return {"state": "finished", "exit_code": code, "started_at": iso(T0),
            "heartbeat": iso(T0)}


def running(now, age=0):
    beat = iso(now - datetime.timedelta(seconds=age))
    return {"state": "running", "exit_code": None, "started_at": iso(T0),
            "heartbeat": beat, "heartbeat_interval_sec": 10}


class Fleet:
    """Records in storage order; :meth:`snapshot` publishes a generation."""

    def __init__(self, seed=0):
        self.rng = random.Random(seed)
        self.specs = []  # [{verstr, parent, values, archived, branch, opt, ts}]
        self.rows = []
        self.states = {}
        self.observed = {}
        self.generation = 0
        self._ids = 0

    # -- records -------------------------------------------------------
    def _fold(self, i):
        spec = self.specs[i]
        meta = {"verstr": spec["verstr"], "timestamp": spec["ts"], "branch": spec["branch"]}
        if spec["parent"]:
            meta["parent"] = spec["parent"]
        log = [{"timestamp": "t", "type": "create", "params": {"opt": spec["opt"]}},
               {"timestamp": "t", "type": "metrics", "values": dict(spec["values"])}]
        row = experiment_row(i + 1, meta, log)
        return dict(row, archived=True) if spec["archived"] else row

    def _values(self):
        rng, values = self.rng, {}
        loss = rng.choice([None, "missing", 0.25, 0.5, 1.0, float("nan"), "x"] + [rng.random()] * 4)
        if loss != "missing":
            values["loss"] = loss
        if rng.random() < 0.5:
            values["acc"] = rng.choice([0.5, rng.random(), rng.random()])
        return values

    def new_verstr(self):
        self._ids += 1
        return f"1.0.0-dev.r{self._ids:06d}"

    def append(self, parent=None, state=None, verstr=None):
        verstr = verstr or self.new_verstr()
        self.specs.append({
            "verstr": verstr, "parent": parent, "values": self._values(),
            "archived": False, "branch": f"b{self.rng.randrange(3)}",
            "opt": self.rng.choice(["adam", "sgd"]),
            "ts": f"2026-01-01T00:{self.rng.randrange(60):02d}:{self.rng.randrange(60):02d}Z",
        })
        self.rows.append(self._fold(len(self.specs) - 1))
        self.states[verstr] = state
        self.observed[verstr] = None
        return verstr

    def edit(self, i, **changes):
        self.specs[i].update(changes)
        self.rows[i] = self._fold(i)

    def remove(self, i):
        verstr = self.specs.pop(i)["verstr"]
        del self.rows[i]
        del self.states[verstr]
        del self.observed[verstr]
        for j in range(i, len(self.rows)):
            self.rows[j] = dict(self.rows[j], idx=j + 1)

    def set_state(self, i, state):
        self.states[self.specs[i]["verstr"]] = state

    def observe(self, i, when):
        self.observed[self.specs[i]["verstr"]] = when

    def index(self, verstr):
        return next(i for i, s in enumerate(self.specs) if s["verstr"] == verstr)

    def ancestors(self, verstr):
        parent_of = {s["verstr"]: s["parent"] for s in self.specs}
        out, cursor = [], parent_of.get(verstr)
        while cursor and cursor not in out:
            out.append(cursor)
            cursor = parent_of.get(cursor)
        return out

    def snapshot(self):
        self.generation += 1
        return IndexSnapshot.build(
            APP, self.generation, list(self.rows), dict(self.states),
            observed_at=dict(self.observed),
        )

    # -- random workload -----------------------------------------------
    def seed(self, n, now, sweeps=4, live=10):
        roots = [self.append(state=running(now)) for _ in range(sweeps)]
        for _ in range(n - sweeps):
            parent = self.rng.choice(roots) if self.rng.random() < 0.3 else None
            self.append(parent=parent, state=self.rng.choice([finished(0), finished(1), None]))
        for i in self.rng.sample(range(sweeps, n), live):
            self.set_state(i, running(now, self.rng.choice([0, 30, 50])))
        return roots

    def mutate(self, now, count, removals=True, reparent=True):
        """*count* random record changes, as one refresh would see them."""
        rng = self.rng
        for _ in range(count):
            n = len(self.specs)
            i = rng.randrange(n)
            op = rng.choice(["append", "child", "metric", "finish", "start", "beat",
                             "archive", "observe", "remove", "reparent", "orphan"])
            if op == "append":
                self.append(state=rng.choice([None, running(now)]))
            elif op == "child":
                self.append(parent=self.specs[i]["verstr"], state=running(now))
            elif op == "metric":
                self.edit(i, values=self._values())
            elif op == "finish":
                self.set_state(i, finished(rng.choice([0, 3])))
            elif op == "start":
                self.set_state(i, running(now, rng.choice([0, 80])))
            elif op == "beat":
                self.set_state(i, running(now))
            elif op == "archive":
                self.edit(i, archived=not self.specs[i]["archived"])
            elif op == "observe":
                self.observe(i, now - datetime.timedelta(seconds=rng.choice([1, 500])))
            elif op == "remove" and removals and n > 20:
                self.remove(n - 1 - rng.randrange(3))
            elif op == "reparent" and reparent:
                self._reparent(i)
            elif op == "orphan":
                # A child whose parent shows up only in a later generation.
                self.append(parent=f"1.0.0-dev.later{rng.randrange(3)}", state=finished())
                if rng.random() < 0.5:
                    late = f"1.0.0-dev.later{rng.randrange(3)}"
                    if late not in self.states:
                        self.append(state=finished(), verstr=late)

    def _reparent(self, i):
        verstr = self.specs[i]["verstr"]
        allowed = [s["verstr"] for s in self.specs
                   if s["verstr"] != verstr and verstr not in self.ancestors(s["verstr"])]
        parent = self.rng.choice(allowed + [None])
        self.edit(i, parent=parent)
