"""A study's leaves in fgm's tree (:mod:`uiload.fgm_tree`): its trial, refit
and assembler runs (level 3) and the pod run each one that ever started
opened under it (level 4), with their fates, times, metrics and the
``health``/``state`` tags fgm publishes (plan 28 §1 3b-3e).

``health`` (trial, refit_single) is ok/warn/unstable; BCA's unstable share
grows with the trade date (incident 1). ``state`` (trial, assembler,
refit_single) is rare. Refits and the assembler lag the trials of a date in
flight, and queue longer.
"""
MINUTE = 60
REFITS = ("refit", "refit_single", "refit_expansion")
HEALTH_KINDS = frozenset({"trial", "refit_single"})
STATE_KINDS = frozenset({"trial", "assembler", "refit_single"})
STATES = ("nonfinite", "collapsed", "degenerate")
POD_SCRIPTS = {"trial": "train_trial.py", "assembler": "assemble.py"}
DURATION_SEC = {"trial": (300, 1500), "assembler": (120, 600)}
REFIT_DURATION_SEC = (600, 2400)
ERRORS = ("memory ceiling 64Gi reached", "submission exhausted 3 retries",
          "pod died without S3 result (retries exhausted)", "assembler OOM at 128Gi, cannot escalate")
EVICTION_WINDOW_SEC = 70 * MINUTE
LEFTOVERS = (("released", 0.01), ("created", 0.01), ("stuck", 0.001))
FAILED_SHARE = 0.04
RETRIED_SHARE = 0.03
DEFINES = {"value": {"goal": "max"}, "cv*": {"hidden": True}, "health.*": {"hidden": True}}


class Leaf:
    def __init__(self, launch, study, tags, date_frac, phase):
        self.launch, self.study, self.tags = launch, study, tags
        self.rng, self.now = launch.rng, launch.now
        self.date_frac = date_frac  # 0 at the first trade date, 1 at the last
        self.start, self.ended, self.done = phase

    def child(self, kind, name, params=None):
        ended = self.ended if kind == "trial" else self.ended ** 2  # refits lag the trials
        spec = self.launch.add(self.study, kind, name, self.tags, self._params(kind, params),
                               created_at=self.start + self.rng.uniform(0, 30),
                               defines=DEFINES if kind == "trial" else {},
                               fate=self._fate(ended))
        self._times(spec, kind)
        if spec["fate"] in ("succeeded", "failed"):
            self._results(spec, kind)
        if spec["fate"] == "released":
            spec["signal"] = "SIGTERM"
        return spec

    def _params(self, kind, extra):
        rng = self.rng
        if kind == "trial":  # the sampled hyperparameters
            return dict(extra, lr=round(10 ** rng.uniform(-4, -2), 6), n_layers=rng.randint(2, 6),
                        dropout=round(rng.uniform(0, 0.4), 3))
        return {"n_members": 8 if kind == "assembler" else rng.choice((4, 8, 16))}

    def _fate(self, ended):
        rng = self.rng
        if rng.random() < ended:
            x = rng.random()
            if x < FAILED_SHARE:
                return "failed"
            threshold, leftovers = FAILED_SHARE, () if self.launch.live else LEFTOVERS
            for fate, share in leftovers:
                threshold += share
                if x < threshold:
                    return fate
            return "succeeded"
        if rng.random() < 0.75:
            return "running"
        return "released" if rng.random() < 0.3 else "created"

    def _times(self, spec, kind):
        rng, fate, created = self.rng, spec["fate"], spec["created_at"]
        if fate == "created":
            return
        if self.done:
            lo, hi = REFIT_DURATION_SEC if kind in REFITS else DURATION_SEC[kind]
            started = created + rng.uniform(5, 600) * (1 if kind == "trial" else 3)
            end = started + rng.uniform(lo, hi)
        else:
            started = created + rng.uniform(0, 0.5) * (self.now - created)
            end = started + rng.uniform(0.3, 1.0) * (self.now - started)
        spec["started_at"] = started
        if fate in ("succeeded", "failed"):
            spec["finished_at"] = end
        elif fate == "released":
            spec["released_at"] = (rng.uniform(max(started, self.now - EVICTION_WINDOW_SEC), self.now)
                                   if self.launch.live else end)
            spec["resume_count"] = rng.choice((0, 0, 1, 2))
        if fate == "succeeded" and rng.random() < RETRIED_SHARE:
            spec["resume_count"] = rng.randint(1, 3)

    def _results(self, spec, kind):
        rng = self.rng
        if spec["fate"] == "failed":
            spec.update(exit_code=1, error={"type": "RuntimeError", "message": rng.choice(ERRORS)},
                        metrics={"peak_rss_mb": round(rng.uniform(4000, 64000))})
            return
        spec["exit_code"] = 0
        health = self._health() if kind in HEALTH_KINDS else None
        if health:
            spec["tags"]["health"] = health
        if kind in STATE_KINDS and rng.random() < (0.3 if health == "unstable" else 0.01):
            spec["tags"]["state"] = rng.choice(STATES)
        spec["metrics"] = self._metrics(kind, health)

    def _health(self):
        unstable = 0.01 + (0.12 * self.date_frac if self.tags["group"] == "BCA" else 0.0)
        x = self.rng.random()
        return "unstable" if x < unstable else "warn" if x < unstable + 0.08 else "ok"

    def _metrics(self, kind, health):
        rng = self.rng
        if kind == "assembler":
            return {"nn.g_out": round(rng.uniform(0.3, 1.2), 4),
                    **{f"fi.{f}": round(rng.random(), 4) for f in ("carry", "momentum", "value")}}
        value = round(rng.gauss(0.6, 0.3) - (0.5 if health == "unstable" else 0.0), 4)
        metrics = {"value": value, "score": round(value + rng.gauss(0, 0.05), 4),
                   "peak_rss_mb": round(rng.uniform(2000, 32000)),
                   "health.loss_diverge_rel": round(rng.uniform(0, 1.5 if health else 0.5), 3),
                   "health.gnorm_spike_frac": round(rng.uniform(0, 0.3), 3)}
        if kind != "trial":
            metrics["n_models_fitted"] = rng.choice((4, 8, 16))
        return metrics

    def pod(self, child):
        """The pod run *child*'s last attempt opened under it, unless it never started."""
        fate = child["fate"]
        if fate == "created":
            return
        kind = child["tags"]["kind"]
        script = POD_SCRIPTS.get(kind, "refit.py")
        rng, n = self.rng, len(self.launch.specs)
        tags = dict(self.tags, **{"pod.name": f"fgm-{kind}-{n:06x}", "node.name": f"ip-10-0-{n % 250}",
                                  "attempt": str(child["resume_count"] + 1),
                                  "k8s.namespace": "fgm"})
        end = child["finished_at"] or child["released_at"]
        pod = self.launch.add(child, f"pod/{script}", f"pod/{script}", tags, {"script": script},
                              fate=fate, created_at=child["started_at"] - 1,
                              started_at=child["started_at"], finished_at=end)
        if fate == "released":  # the pod's own run ends with the SIGTERM
            pod.update(fate="failed", exit_code=143, signal="SIGTERM")
        elif fate in ("succeeded", "failed"):
            pod["exit_code"] = 0 if fate == "succeeded" else 137
            if fate == "failed":
                pod["signal"] = "SIGKILL"
        if end is not None:
            wall = end - child["started_at"]
            peak = rng.uniform(2000, 40000)
            pod["metrics"] = {"res.wall_s": round(wall, 1), "res.cpu_util": round(rng.random(), 3),
                              "res.mem_peak_mb": round(peak), "res.mem_headroom":
                              round(1 - peak / 32000, 3)}
