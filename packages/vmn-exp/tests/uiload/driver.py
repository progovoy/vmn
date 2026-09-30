"""A uiload session: data root, seeded history, the ``vmn-exp ui`` server, the
live job population, the API prober, and the checks that tie them together.

``run_live`` is for watching (terminal table + a browser on the printed URL);
``run_check`` runs a profile for its duration and returns a JSON report with
latency budgets, oracle-vs-API mismatches and (optionally) browser metrics.
"""
import collections
import json
import os
import threading
import time

from uiload import live_view, oracle, slo
from uiload.probe import Probe, fetch_all_rows, freshness_lag, status_counts
from uiload.spawner import Spawner, pack_jobs  # noqa: F401  (re-exported)
from uiload.ui_server import UIServer

APP = "loadapp"
WS = "uiload"
LIVE_Q = 'name ~ "live-"'
HIST_Q = 'name ~ "hist-"'
TICK_SEC = 0.5


class Session:
    def __init__(self, profile, run_dir, rng_seed=0, port=None, per_process=20):
        self.profile, self.run_dir = profile, os.path.abspath(run_dir)
        self.root = os.path.join(self.run_dir, WS)
        os.makedirs(os.path.join(self.root, ".git"), exist_ok=True)
        self.seeded, self.api_hist = {}, {}
        self.ui = UIServer(self.root, self.run_dir, profile.min_stale_sec, port=port)
        self.spawner = Spawner(profile, self.root, APP, self.run_dir, rng_seed, per_process)
        self.latency = live_view.LatencyWindow()

    def start(self):
        if self.profile.seeded_runs:
            from uiload.seeder import seed_profile

            t0 = time.monotonic()
            self.seeded = seed_profile(self.root, self.profile, app=APP)
            self.seeded["seed_sec"] = round(time.monotonic() - t0, 1)
        if not self.seeded:
            self.spawner.tick()  # first live runs make the app exist for an empty root
        self.ui.start()
        if self.seeded:  # live jobs start once the history is served, not while it indexes
            self.seeded["index_ready_sec"] = self.ui.wait_indexed(WS, APP, self.seeded["total"])
            # History is static: count it once, not on every view refresh.
            hist = fetch_all_rows(self.ui.base_url, WS, APP, query=HIST_Q, archived=True)
            self.api_hist = status_counts(hist)
        self.started = time.monotonic()
        return self

    def compare(self):
        """Live rows as the API shows them vs the oracle's expectation."""
        rows = fetch_all_rows(self.ui.base_url, WS, APP, query=LIVE_Q)
        now = time.time()
        api = {r.get("name"): r.get("status") for r in rows}
        wants = {job_id: oracle.expected_status(events, now, self.profile.stale_sec)
                 for job_id, events in oracle.load_events(self.run_dir).items()}
        settled = {job_id: want for job_id, want in wants.items() if want is not None}
        mismatches = [f"{job_id}: expected {want}, api {api.get(job_id)}"
                      for job_id, want in settled.items() if api.get(job_id) != want]
        return {"rows": rows, "api_live": status_counts(rows),
                "expected": dict(collections.Counter(settled.values())),
                "ambiguous": len(wants) - len(settled), "mismatches": sorted(mismatches),
                "compared": len(settled)}

    def snapshot(self):
        cmp = self.compare()
        return live_view.Snapshot(
            elapsed_sec=time.monotonic() - self.started, processes=len(self.spawner.groups),
            spawned_jobs=self.spawner.spawned_jobs, expected=cmp["expected"],
            ambiguous=cmp["ambiguous"], api_live=cmp["api_live"], api_hist=self.api_hist,
            mismatches=cmp["mismatches"], latency=self.latency.stats(),
            freshness_sec=freshness_lag(cmp["rows"]),
        )

    def stop(self):
        """Tear everything down; the pids that were alive, to verify they are gone."""
        pids = self.spawner.pids() + ([self.ui.proc.pid] if self.ui.proc else [])
        self.spawner.teardown()
        self.ui.stop()
        return pids


def _probe_thread(session, stop, out):
    probe = Probe(session.ui.base_url, WS, APP)
    try:
        out["report"] = probe.run(0, session.profile.probe_concurrency, stop_event=stop,
                                  on_sample=session.latency.add)
    except Exception as exc:  # e.g. the API timing out under load: a finding
        out["error"] = repr(exc)[:500]


def _churn(session, stop, out, extra_threads=()):
    """Probe the API while keeping the population alive for the profile's
    duration (0 = until Ctrl-C); returns with the probe stopped."""
    duration = session.profile.duration_sec
    threads = [threading.Thread(target=_probe_thread, args=(session, stop, out), daemon=True),
               *extra_threads]
    for t in threads:
        t.start()
    try:
        while not duration or time.monotonic() - session.started < duration:
            session.spawner.tick()
            time.sleep(TICK_SEC)
    finally:
        stop.set()
        for t in threads:
            t.join(60)


def run_live(profile, run_dir, rng_seed=0, port=None):
    """Churn the profile's population until Ctrl-C (or its duration), redrawing the view."""
    session = Session(profile, run_dir, rng_seed, port).start()
    print(f"uiload: UI at {session.ui.base_url}  (data {session.root})", flush=True)
    stop, out = threading.Event(), {}
    view = threading.Thread(target=live_view.print_loop, args=(session.snapshot, stop), daemon=True)
    try:
        _churn(session, stop, out, [view])
    except KeyboardInterrupt:
        pass
    finally:
        session.stop()
    return out.get("report")


def run_check(profile, run_dir, browser=True, rng_seed=0, port=None):
    """Run *profile* for its duration, then assert-ready report (also ``report.json``)."""
    session = Session(profile, run_dir, rng_seed, port).start()
    stop, out = threading.Event(), {}
    try:
        _churn(session, stop, out)
        session.spawner.tick(accept_new=False)
        report = _final_report(session, out.get("report"), browser)
        if "error" in out:
            report["probe_error"] = out["error"]
    finally:
        leftover = session.stop()
    report["leftover_pids"] = [p for p in leftover if _alive(p)]
    with open(os.path.join(session.run_dir, "report.json"), "w") as f:
        json.dump(report, f, indent=2, default=str)
    return report


def _final_report(session, probe_report, browser):
    cmp = session.compare()
    report = {
        "profile": session.profile.name, "seeded": session.seeded,
        "spawned_jobs": session.spawner.spawned_jobs,
        "probe": probe_report.to_dict() if probe_report else None,
        "slo_violations": slo.evaluate(probe_report, session.profile.name) if probe_report else [],
        **{k: cmp[k] for k in ("api_live", "expected", "ambiguous", "mismatches", "compared")},
    }
    if session.seeded:
        report["api_hist"] = session.api_hist
    if browser:
        from uiload.browser import BrowserChecks

        # A plain (non-wide) run with metrics, so chart_ms measures the same thing each run.
        charted = sorted(r["name"] for r in cmp["rows"]
                         if (r.get("metrics") or {}).get("loss") is not None
                         and (r.get("tags") or {}).get("behavior") != "wide")
        try:
            with BrowserChecks(session.ui.base_url, WS, APP) as checks:
                report["browser"] = checks.run_all(budget=session.profile.name, idle_sec=30,
                                                   run_name=charted[0] if charted else None)
        except Exception as exc:  # a hung page is a finding, not a harness crash
            report["browser"] = {"violations": [f"browser check crashed: {exc!r}"[:500]]}
    return report


def failures(report):
    """Every reason a check-mode *report* fails, flattened."""
    found = list(report["slo_violations"]) + list(report["mismatches"])
    found += report.get("browser", {}).get("violations", [])
    found += [f"leftover process {p}" for p in report["leftover_pids"]]
    if report.get("probe_error"):
        found.append(f"probe crashed: {report['probe_error']}")
    return found


def _alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
