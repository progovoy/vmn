"""A leaderboard fleet for plan 28 FS/N4 tests: every run carries a
``kind`` tag, finished runs carry start and end times (so their durations
never move with the clock), waiting runs none."""
import datetime

from leaderboard_fleet import Fleet, iso, running

KINDS = ["trial", "refit", None]


def ended_after(now, seconds, code=0):
    """A finished run state: ran *seconds*, ended at *now*."""
    start = now - datetime.timedelta(seconds=seconds)
    return {"state": "finished", "exit_code": code, "started_at": iso(start),
            "finished_at": iso(now), "heartbeat": iso(now)}


class DurationFleet(Fleet):
    def _fold(self, i):
        spec = self.specs[i]
        if "kind" not in spec:
            spec["kind"] = self.rng.choice(KINDS)
        row = super()._fold(i)
        return dict(row, tags={"kind": spec["kind"]} if spec["kind"] else {})

    def add(self, parent, kind, state, ts="2026-01-01T00:00:00Z"):
        verstr = self.new_verstr()
        self.specs.append({"verstr": verstr, "parent": parent, "values": {}, "archived": False,
                           "branch": "b0", "opt": "adam", "kind": kind, "ts": ts})
        self.rows.append(self._fold(len(self.specs) - 1))
        self.states[verstr], self.observed[verstr] = state, None
        return verstr

    def seed_tree(self, now, jobs=4, kids=30):
        """*jobs* outer runs of *kids* children, most of them ended."""
        roots = [self.add(None, None, self.ended(now)) for _ in range(jobs)]
        for root in roots:
            for _ in range(kids):
                self.add(root, self.rng.choice(KINDS), self._state(now),
                         ts=self.specs[0]["ts"] if self.rng.random() < 0.5 else
                         "2026-03-01T11:00:00Z")
        return roots

    def _state(self, now):
        roll = self.rng.random()
        if roll < 0.1:
            return None
        if roll < 0.2:
            return running(now, self.rng.choice([0, 20]))
        return self.ended(now)

    def churn(self, now, count):
        """*count* record changes that keep every finished run's times fixed."""
        rng = self.rng
        for _ in range(count):
            i = rng.randrange(len(self.specs))
            parents = [s["verstr"] for s in self.specs if s["parent"] is None]
            op = rng.choice(["child", "finish", "start", "wait", "kind", "archive", "remove",
                             "reparent"])
            if op == "child":
                self.add(rng.choice(parents), rng.choice(KINDS), self._state(now))
            elif op == "finish":
                self.set_state(i, self.ended(now))
            elif op == "start":
                self.set_state(i, running(now))
            elif op == "wait":
                self.set_state(i, None)
            elif op == "kind":
                self.edit(i, kind=rng.choice(KINDS))
            elif op == "archive":
                self.edit(i, archived=not self.specs[i]["archived"])
            elif op == "remove" and len(self.specs) > 20:
                self.remove(len(self.specs) - 1 - rng.randrange(3))
            elif op == "reparent" and self.specs[i]["parent"] is not None:
                self.edit(i, parent=rng.choice(parents))
