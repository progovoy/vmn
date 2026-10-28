"""fgm's run tree (plan 28 §0-§2, B0) as a deterministic plan of run specs.

    launch → date → study → trial / refit* / assembler → pod     (levels 0-4)
    launch → cost_report                                        (level 1)

``launch_runs(profile, n, now)`` is launch *n*'s runs, parents first, a pure
function of ``(profile, n, now)``; ``plan_runs`` every launch's. A spec is a
dict: ``verstr``, ``code_verstr``, ``commit``, ``parent``, ``level``,
``name``, ``tags`` (``kind`` everywhere; the Phase 0 ``trade_date`` from the
date down, ``group``/``target`` from the study down; ``health``/``state`` on
some trials), ``params``, ``metrics`` (final values), ``defines``
(``define_metric`` fields by name), ``fate`` and its times (epoch seconds).

``fate`` is what the run's files say: ``succeeded``, ``failed``,
``running``, ``stuck``, ``created`` (pre-registered, never started) or
``released`` (handed back, ``run.release()``: derives ``created``). The
newest ``live_launches`` launches are live as of *now*: ``live_done`` dates
done, the next ``live_inflight`` in flight (the oldest mostly ended, the
newest mostly waiting) with an eviction wave of released runs in the last
hour. Finished launches leave a few released, never-started and orphaned
(stuck) runs behind. Stdlib only, so seeding workers start fast.
"""
import dataclasses
import hashlib
import random

from uiload import fgm_leaf

MINUTE, HOUR, DAY = 60, 3600, 86400
BASE_VERSION = "0.9.0"
DATE_SEC = 40 * MINUTE  # a finished launch's dates, one after the other
LAUNCH_GAP_SEC = 2 * DAY
INFLIGHT_STAGGER_SEC = 3 * MINUTE
TARGETS = ("h30", "h180", "h360")
GROUPS = ("BCA", "BCAFX", "XS")
TABLES = ("BCA", "BCAFX", "FXMacro", "XS")
MODEL_TYPES = ("RegimeNN", "GBM")
COVERAGE = {"complete": 80, "partial": 15, "unknown": 5}


@dataclasses.dataclass(frozen=True)
class FgmProfile:
    name: str
    launches: int
    live_launches: int  # the newest ones
    dates: int  # per launch
    live_done: int  # dates a live launch has done
    live_inflight: int  # dates it has in flight
    targets: int
    groups: int
    trials: int  # per study, beside 3 refits and an assembler
    probe_requests: int  # timed requests per route (uiload.probe_fgm)


PROFILES = {p.name: p for p in (
    FgmProfile("fgm", 32, 4, 60, 20, 20, 2, 2, 36, 50),
    FgmProfile("fgm-small", 3, 1, 60, 20, 20, 2, 2, 36, 20),
    FgmProfile("fgm-tiny", 2, 1, 4, 2, 2, 1, 2, 4, 5),
)}


def get_profile(name):
    return PROFILES[name]


def derived_status(fate):
    """The status a run of *fate* derives: a released run waits again."""
    return "created" if fate == "released" else fate


def launches(specs):
    """``(live launch, ended launch)`` verstrs of *specs*: the first of each."""
    heads = [s for s in specs if s["tags"]["kind"] == "launch"]
    return (next(s["verstr"] for s in heads if s["fate"] == "running"),
            next(s["verstr"] for s in heads if s["fate"] == "succeeded"))


def trade_date(d):
    return f"{2021 + d // 12}-{d % 12 + 1:02d}-01"


def plan_runs(profile, now):
    """Every launch's runs, oldest launch first."""
    for n in range(profile.launches):
        yield from launch_runs(profile, n, now)


def launch_runs(profile, n, now):
    return _Launch(profile, n, now).build()


def _hex(*parts):
    return hashlib.sha1(":".join(map(str, parts)).encode()).hexdigest()


class _Launch:
    def __init__(self, profile, n, now):
        self.p, self.n, self.now = profile, n, now
        self.rng = random.Random(f"fgm:{n}")
        self.live = n >= profile.launches - profile.live_launches
        self.commit = _hex("fgm", "commit", n)
        self.code = f"{BASE_VERSION}-dev.{self.commit[:7]}.{_hex('fgm', 'diff', n)[:7]}"
        self.launch_id = f"wf{n:03d}"
        self.table, self.model_type = TABLES[n % len(TABLES)], MODEL_TYPES[n % 2]
        if self.live:
            self.start = now - profile.live_done * DATE_SEC - HOUR
        else:
            self.start = now - (profile.launches - n + 1) * LAUNCH_GAP_SEC
        self.specs = []

    def add(self, parent, kind, name, tags=None, params=None, **fields):
        number = len(self.specs) + 1
        spec = {
            "verstr": self.code if number == 1 else f"{self.code}.r{number}",
            "code_verstr": self.code, "commit": self.commit,
            "parent": parent and parent["verstr"],
            "level": 0 if parent is None else parent["level"] + 1,
            "name": name, "tags": dict(tags or {}, kind=kind), "params": params or {},
            "metrics": {}, "defines": {}, "fate": "succeeded", "created_at": self.start,
            "started_at": None, "finished_at": None, "released_at": None,
            "resume_count": 0, "signal": None, "error": None, "exit_code": None,
        }
        spec.update(fields)
        self.specs.append(spec)
        return spec

    def build(self):
        p = self.p
        launch = self.add(None, "launch", f"launch/{self.launch_id}",
                          {"mode": "walk_forward", "launch_id": self.launch_id},
                          {"table_name": self.table, "model_type": self.model_type,
                           "n_dates": p.dates, "progress_unit": "dates"}, started_at=self.start)
        planned = p.live_done + p.live_inflight if self.live else p.dates
        dates = [self.date(launch, d) for d in range(planned)]
        done = sum(d["fate"] == "succeeded" for d in dates)
        failed = sum(d["fate"] == "failed" for d in dates)
        launch["metrics"] = {"progress": done + failed, "progress_total": p.dates,
                             "wf.dates_done": done, "wf.dates_failed": failed,
                             "wf.dates_total": p.dates}
        if self.live:
            launch["fate"] = "running"
        else:
            launch["finished_at"] = self.start + p.dates * DATE_SEC + 10 * MINUTE
            self.cost_report(launch)
        return self.specs

    def _phase(self, d):
        """``(date start, share of its runs ended, whether it is done)``."""
        p = self.p
        if not self.live or d < p.live_done:
            return self.start + d * DATE_SEC, 1.0, True
        j = d - p.live_done
        return (self.now - (p.live_inflight - j) * INFLIGHT_STAGGER_SEC,
                1 - (j + 0.5) / p.live_inflight, False)

    def date(self, launch, d):
        phase = self._phase(d)
        start, _, done = phase
        day = trade_date(d)
        params = {"trade_date": day, "model_type": self.model_type, "table_name": self.table}
        date = self.add(launch, "date", f"{self.launch_id}/{day}", {"trade_date": day}, params,
                        created_at=start, started_at=start)
        for target in TARGETS[:self.p.targets]:
            for group in GROUPS[:self.p.groups]:
                self.study(date, d, target, group, phase)
        if not done:
            date["fate"] = "running"
        else:
            if not self.live and self.rng.random() < 0.02:
                date.update(fate="failed", exit_code=1,
                            error={"type": "RuntimeError", "message": "prep failed or timed out"})
            date["finished_at"] = start + DATE_SEC
        return date

    def study(self, date, d, target, group, phase):
        start, _, done = phase
        day = date["tags"]["trade_date"]
        tags = {"trade_date": day, "group": group, "target": target}
        params = dict(tags, n_trials=self.p.trials, model_type=self.model_type,
                      table_name=self.table, progress_unit="trials",
                      **{"seed.key": _hex(day, target, group)[:8]})
        study = self.add(date, "study", f"study/{day}/{target}/{group}", tags, params,
                         created_at=start, started_at=start, defines={"best_value": {"goal": "max"}})
        leaf = fgm_leaf.Leaf(self, study, tags, d / max(1, self.p.dates - 1), phase)
        children = [leaf.child("trial", f"trial/{t}", {"trial_id": t}) for t in range(self.p.trials)]
        children += [leaf.child(kind, kind) for kind in fgm_leaf.REFITS]
        children.append(leaf.child("assembler", "assembler"))
        for child in children:
            leaf.pod(child)
        trials = [c for c in children if c["tags"]["kind"] == "trial"]
        values = [c["metrics"]["value"] for c in trials if "value" in c["metrics"]]
        ended_trials = [c for c in trials if c["fate"] in ("succeeded", "failed")]
        study["metrics"] = {"progress": len(ended_trials), "progress_total": self.p.trials,
                            "study.trials_done": len(ended_trials),
                            "study.trials_failed": sum(c["fate"] == "failed" for c in trials)}
        if values:
            study["metrics"]["best_value"] = max(values)
        if done:
            study["finished_at"] = start + DATE_SEC - MINUTE
        else:
            study["fate"] = "running"

    def cost_report(self, launch):
        rng, end = self.rng, launch["finished_at"]
        stages = {f"stage_{s}_cost_usd": round(rng.uniform(20, 900), 2)
                  for s in ("prep", "train", "refit", "assemble")}
        metrics = dict(stages, total_cost_usd=round(sum(stages.values()), 2),
                       waste_idle_usd=round(rng.uniform(1, 80), 2))
        coverage = rng.choices(list(COVERAGE), weights=list(COVERAGE.values()))[0]
        self.add(launch, "cost_report", f"cost_report/{self.launch_id}",
                 {"coverage": coverage, "launch_id": self.launch_id, "job_type": "walk_forward"},
                 metrics=metrics, created_at=end + MINUTE, started_at=end + MINUTE,
                 finished_at=end + 3 * MINUTE)
