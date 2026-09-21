"""Streamed metrics must be appended, never read-merged-and-rewritten.

`vmn exp run` tails ``$VMN_METRICS_FILE`` and flushes whatever the child wrote
on every poll. Doing that as load-merged-log + rewrite-log.yml duplicates every
entry already stored in a per-writer JSONL file — once per flush — and races any
other writer. These tests pin append-only behavior.
"""
import os

from helpers import (
    _PY,
    _bootstrap,
    _exec_script,
    _experiment,
    _storage,
    extract_dev_verstr,
)


def _log(app_layout, verstr):
    from version_stamp.core.experiment_log import load_log

    return load_log(_storage(app_layout), app_layout.app_name, verstr)


def _types(log):
    return [e.get("type") for e in log]


def _emitter(app_layout, name="emit.py", flushes=3, pause=1.2):
    """A child that writes one metrics line per poll window, so the supervisor
    flushes several times during one run."""
    return _exec_script(
        app_layout,
        name,
        "import os, time\n"
        'f = os.environ["VMN_METRICS_FILE"]\n'
        f"for i in range({flushes}):\n"
        '    open(f, "a").write("step=%d loss=%.2f\\n" % (i, 0.5 - i * 0.1))\n'
        f"    time.sleep({pause})\n",
    )


def test_streamed_metrics_do_not_duplicate_earlier_entries(app_layout, capfd):
    """The `created` entry must appear exactly once, however many flushes ran."""
    _bootstrap(app_layout)
    script = _emitter(app_layout)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="run", run_cmd=[_PY, script]) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    types = _types(_log(app_layout, verstr))
    assert types.count("create") == 1, types
    assert types.count("run") == 1, types
    assert types.count("metrics") == 3, types


def test_every_streamed_metric_is_recorded_once_in_order(app_layout, capfd):
    _bootstrap(app_layout)
    script = _emitter(app_layout)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="run", run_cmd=[_PY, script]) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    metrics = [e for e in _log(app_layout, verstr) if e.get("type") == "metrics"]
    assert [e.get("step") for e in metrics] == [0, 1, 2]
    assert [e["values"]["loss"] for e in metrics] == [0.5, 0.4, 0.3]


def test_ingest_does_not_rewrite_the_legacy_log_file(app_layout, capfd):
    """Appends belong in the writer's own JSONL, so a shared log.yml is never
    rewritten — that rewrite is what clobbers a concurrent writer."""
    _bootstrap(app_layout)
    script = _emitter(app_layout, flushes=2)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="run", run_cmd=[_PY, script]) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    exp_dir = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "experiments", verstr
    )
    assert not os.path.exists(os.path.join(exp_dir, "log.yml")), os.listdir(exp_dir)
    jsonl = [n for n in os.listdir(exp_dir) if n.startswith("log.") and n.endswith(".jsonl")]
    assert jsonl, os.listdir(exp_dir)


def test_a_concurrent_writers_entries_survive_ingest(app_layout, capfd):
    """Another writer appending during the run must not be lost."""
    _bootstrap(app_layout)
    script = _emitter(app_layout, flushes=3)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="run", run_cmd=[_PY, script]) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    # Simulate the other writer after the fact: its own JSONL file, which the
    # merge must pick up and no later ingest may overwrite.
    storage = _storage(app_layout)
    storage.append_log_entry(
        app_layout.app_name, verstr, "other-pod", {"type": "note", "text": "from afar"}
    )
    log = _log(app_layout, verstr)
    assert any(e.get("text") == "from afar" for e in log), _types(log)
    assert _types(log).count("create") == 1, _types(log)
