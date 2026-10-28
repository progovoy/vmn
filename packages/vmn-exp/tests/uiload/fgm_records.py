"""fgm's planned runs (:mod:`uiload.fgm_tree`) as the records the SDK writes:
``metadata.yml``, the JSONL log (create with params, tags, ``define_metric``,
step-less metrics, error) and ``run_state.yml`` (none for a pre-registered
run that never started), and the index snapshot those records fold into.

    build_run(spec, now, app) -> (metadata, log entries, run state or None)
    snapshot(profile, now) -> (IndexSnapshot, specs)   # in memory, for benches

A live run's heartbeat is *now*: it reads ``running`` while *now* is
recent, or while its *live_interval_sec* says it may beat that rarely
(:mod:`uiload.seed_fgm` keeps a seeded store live that way).
"""
import datetime

from vmn_exp.core import status as status_mod
from vmn_exp.core.fold import fold_log
from vmn_exp.core.index import snapshot_of_folds
from vmn_exp.core.index_snapshot import IndexSnapshot
from vmn_exp.core.index_views import SIDE_TABLES
from vmn_exp.core.run_error import slim_run_state

from uiload import fgm_tree
from uiload.seed_records import iso

APP = "fastglobalmacro"
HEARTBEAT_SEC = 30
STUCK_AFTER_SEC = 120  # an orphan's last beat after its start


def metadata(app, spec):
    """``metadata.yml`` of a git-free (from-snapshot) run, as a dict."""
    meta = {"app_name": app, "base_commit": spec["commit"], "base_version": fgm_tree.BASE_VERSION,
            "branch": "main", "code_verstr": spec["code_verstr"], "dirty_states": [],
            "format_version": 2, "from_snapshot": True, "name": spec["name"], "note": None,
            "remote": None, "timestamp": iso(spec["created_at"]), "verstr": spec["verstr"]}
    if spec["parent"]:
        meta["parent"] = spec["parent"]
    return meta


def log_entries(spec, now):
    t = spec["created_at"]
    entries = [{"timestamp": iso(t + 0.001), "type": "create", "note": None,
                "params": spec["params"]},
               {"timestamp": iso(t + 0.002), "type": "tags", "set": spec["tags"]}]
    entries += [{"timestamp": iso(t + 0.003), "type": "define_metric", "name": name, **fields}
                for name, fields in spec["defines"].items()]
    if spec["metrics"]:
        at = spec["finished_at"] or spec["released_at"] or now
        entries.append({"timestamp": iso(at), "type": "metrics", "values": spec["metrics"]})
    if spec["error"]:
        entries.append({"timestamp": iso(spec["finished_at"]), "type": "error",
                        "exception": spec["error"]["type"], "message": spec["error"]["message"]})
    return entries


def last_write(spec, now):
    """When the run's process last wrote its run state (its store mtime)."""
    fate = spec["fate"]
    if fate == "running":
        return now
    if fate == "stuck":
        return spec["started_at"] + STUCK_AFTER_SEC
    return spec["released_at"] if fate == "released" else spec["finished_at"]


def freeze_clock(patch, now):
    """Derive statuses as of *now* (epoch seconds) under the monkeypatch
    *patch*; returns *now* as a datetime."""
    at = datetime.datetime.fromtimestamp(now, datetime.timezone.utc)
    patch.setattr(status_mod, "_now", lambda when=None: when or at)
    return at


def run_state(spec, now, live_interval_sec=HEARTBEAT_SEC):
    """The run's ``run_state.yml``, None when it never started; a running
    one's heartbeat interval is *live_interval_sec*."""
    fate = spec["fate"]
    if fate == "created":
        return None
    beat = last_write(spec, now)
    state = {"state": "running", "command": ["python", spec["name"]],
             "pid": 4242, "host": "fgm-node",
             "started_at": iso(spec["started_at"]), "heartbeat": iso(beat),
             "heartbeat_seq": int((beat - spec["started_at"]) // HEARTBEAT_SEC),
             "heartbeat_interval_sec": live_interval_sec if fate == "running" else HEARTBEAT_SEC}
    if spec["resume_count"]:
        state["resume_count"] = spec["resume_count"]
    duration = round(beat - spec["started_at"], 3)
    if fate == "released":
        state.update(state="released", end_reason="released", released_at=iso(beat),
                     duration_sec=duration)
    elif fate in ("succeeded", "failed"):
        state.update(state="finished", exit_code=spec["exit_code"] or 0,
                     finished_at=iso(beat), duration_sec=duration)
        if spec["error"]:
            state["error"] = dict(spec["error"])
    if spec["signal"]:
        state["signal"] = spec["signal"]
    return state


def build_run(spec, now, app=APP, live_interval_sec=HEARTBEAT_SEC):
    return metadata(app, spec), log_entries(spec, now), run_state(spec, now, live_interval_sec)


def snapshot(profile, now, app=APP):
    """The index snapshot of *profile*'s store as of *now*, built in memory
    the way the index folds each record, and the specs in storage order."""
    specs = list(fgm_tree.plan_runs(profile, now))
    states = {}

    def folds():
        for i, spec in enumerate(specs):
            meta, entries, state = build_run(spec, now, app)
            states[spec["verstr"]] = slim_run_state(state)
            yield i + 1, meta, fold_log(entries)

    snap = snapshot_of_folds(app, folds(), lambda rows: (states, {}))
    return snap, specs


def next_generation(snap, finished, now):
    """*snap*'s next generation in which the runs *finished* (verstrs)
    ended succeeded at *now*; every other row and state is the same object
    (the index's identity contract), so a cache moves on by the delta."""
    states = dict(snap.run_states)
    for verstr in finished:
        states[verstr] = dict(states[verstr], state="finished", exit_code=0,
                              finished_at=iso(now), heartbeat=iso(now))
    return IndexSnapshot.build(
        snap.app_name, snap.generation + 1, snap.rows, states, snap.create_notes,
        snap.run_state_observed_at, **{name: getattr(snap, name) for name in SIDE_TABLES})
