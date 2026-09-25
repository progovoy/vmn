#!/usr/bin/env python3
"""Create a temporary repo with realistic experiment data for UI testing.

Usage:
    python3 tests/seed_ui_test_data.py

Then start the UI:
    vmn ui --repo <printed-path> --no-browser
"""
import os
import pathlib
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from conftest import FSAppLayoutFixture, GitBackend
from helpers import _bootstrap


APP = "demo_app"


def _make_dirty(repo_path, name, content="x"):
    p = os.path.join(repo_path, name)
    pathlib.Path(os.path.dirname(p)).mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        f.write(content)


def seed(tmpdir):
    from version_stamp.exp import start_run

    layout = FSAppLayoutFixture(tmpdir, "git")
    layout.app_name = APP
    _bootstrap(layout)

    repo = layout.repo_path
    ids = {}

    # --- 1. Outer run with 8 inner pods ---
    _make_dirty(repo, "sweep.txt", "sweep config")
    with start_run(APP, note="sweep-lr-search", tags={"team": "ml"}) as outer:
        outer.log_params({"expected_pods": 5, "sweep_type": "grid"})
        ids["outer1"] = outer.id

        # 3 succeeded pods
        for i in range(3):
            _make_dirty(repo, f"pod_ok_{i}.txt")
            with start_run(APP, note=f"pod-ok-{i}", nested=True) as pod:
                pod.log_params({"lr": 0.001 * (i + 1), "progress_total": 10})
                for step in range(10):
                    pod.log_metric("progress", step + 1)
                    pod.log_metric("loss", 0.5 - step * 0.04)
                pod.log_metric("accuracy", 0.88 + i * 0.03)
                ids[f"pod_ok_{i}"] = pod.id

        # 2 running pods (finish them partially, then leave running state)
        for i in range(2):
            _make_dirty(repo, f"pod_run_{i}.txt")
            run = start_run(APP, note=f"pod-running-{i}", nested=True)
            run.log_params({"lr": 0.01 * (i + 1), "progress_total": 10})
            for step in range(3 + i * 4):
                run.log_metric("progress", step + 1)
                run.log_metric("loss", 0.8 - step * 0.05)
            # Don't finish — leave as running (will become "created" since no heartbeat daemon)
            # Force-write a running state
            run.finish(exit_code=None)
            ids[f"pod_run_{i}"] = run.id

        # 1 failed pod
        _make_dirty(repo, "pod_fail.txt")
        with start_run(APP, note="pod-failed", nested=True) as pod:
            pod.log_params({"lr": 0.1, "progress_total": 10})
            pod.log_metric("progress", 2)
            pod.log_metric("loss", 0.9)
            pod.finish(exit_code=1)
            ids["pod_fail"] = pod.id

        # 2 created pods (just create, immediately finish with code 0 to simulate created)
        for i in range(2):
            _make_dirty(repo, f"pod_new_{i}.txt")
            with start_run(APP, note=f"pod-new-{i}", nested=True) as pod:
                ids[f"pod_new_{i}"] = pod.id

    # --- 2. Standalone run with date-like integer params ---
    _make_dirty(repo, "single1.txt", "baseline model")
    with start_run(APP, note="baseline-bert", tags={"team": "nlp"}) as run:
        run.log_params({
            "end_date": 20260531,
            "batch_size": 64,
            "epochs": 50,
            "model": "bert-base",
        })
        run.log_metric("loss", 0.342)
        run.log_metric("accuracy", 0.91)
        run.log_metric("f1_score", 0.887)
        ids["single1"] = run.id

    time.sleep(0.1)

    # --- 3. Second outer run with 3 succeeded pods ---
    _make_dirty(repo, "sweep2.txt", "sweep2 config")
    with start_run(APP, note="sweep-batch-size") as outer2:
        outer2.log_params({"expected_pods": 3, "sweep_type": "random"})
        ids["outer2"] = outer2.id

        for i in range(3):
            _make_dirty(repo, f"pod2_{i}.txt")
            with start_run(APP, note=f"batch-pod-{i}", nested=True) as pod:
                pod.log_params({"batch_size": 16 * (2 ** i), "progress_total": 5})
                for step in range(5):
                    pod.log_metric("progress", step + 1)
                pod.log_metric("loss", 0.3 - i * 0.05)
                pod.log_metric("accuracy", 0.9 + i * 0.02)
                ids[f"pod2_{i}"] = pod.id

    time.sleep(0.1)

    # --- 4. A few more standalone runs at different times ---
    for i, (note, loss, acc) in enumerate([
        ("quick-test", 0.7, 0.65),
        ("tuned-resnet", 0.25, 0.93),
        ("final-submission", 0.19, 0.955),
    ]):
        _make_dirty(repo, f"extra_{i}.txt")
        with start_run(APP, note=note) as run:
            run.log_params({"run_date": 20260901 + i, "model": note})
            run.log_metric("loss", loss)
            run.log_metric("accuracy", acc)
            ids[f"extra_{i}"] = run.id
        time.sleep(0.1)

    print(f"\n{'=' * 60}")
    print(f"Seeded {len(ids)} experiments in: {repo}")
    print(f"App name: {APP}")
    print(f"\nStart the UI with:")
    print(f"  vmn ui --repo {repo} --no-browser")
    print(f"{'=' * 60}\n")

    return repo


if __name__ == "__main__":
    import tempfile
    tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="vmn_ui_test_"))
    print(f"Working in: {tmpdir}")
    seed(tmpdir)
