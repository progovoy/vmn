#!/usr/bin/env python3
"""A realistic training loop, minus the training: what to log and when.

Shows:  params up front, a per-step metric curve, a note, an artifact, and
        system_metrics=True so CPU and memory are sampled on every heartbeat.
        Plain Python — no ML library needed.
Run:    python examples/02_training_loop.py   (inside a git repo with a remote)
App:    writes runs to the vmn app "vmn_examples"
Next:   vmn exp show vmn_examples --latest   (the loss curve and sys_* metrics)
"""
import json
import os
import tempfile
import time

from version_stamp.exp import start_run

APP_NAME = "vmn_examples"
EPOCHS = 10
PARAMS = {"optimizer": "adam", "lr": 0.001, "batch_size": 32, "epochs": EPOCHS}


def fake_epoch(epoch):
    """Stand-in for a real epoch: a smooth curve and a quarter second of work."""
    time.sleep(0.25)
    loss = round(2.0 / (epoch + 2), 4)
    accuracy = round(1.0 - loss / 2.0, 4)
    return loss, accuracy


def log_artifact(run, history):
    """log_artifact copies the file into the run's store, so a temp file works."""
    with tempfile.TemporaryDirectory(prefix="vmn-example-") as tmp:
        path = os.path.join(tmp, "metrics.json")
        with open(path, "w") as f:
            json.dump(history, f, indent=2)
        run.log_artifact(path)


def main():
    # A short heartbeat so the system-metrics sampler ticks a few times inside a
    # run this brief; leave it at the 30s default for real training.
    with start_run(
        APP_NAME,
        note="fake training loop",
        params=PARAMS,
        heartbeat_interval_sec=0.5,
        system_metrics=True,
    ) as run:
        print(f"run id: {run.id}")
        history = []
        for epoch in range(EPOCHS):
            loss, accuracy = fake_epoch(epoch)
            run.log_metrics({"loss": loss, "accuracy": accuracy}, step=epoch)
            history.append({"epoch": epoch, "loss": loss, "accuracy": accuracy})
            print(f"  epoch {epoch}: loss={loss} accuracy={accuracy}")

        run.log_note(f"finished {EPOCHS} epochs, final loss {history[-1]['loss']}")
        log_artifact(run, history)

    print(f"logged: {EPOCHS} steps of loss/accuracy, a note, metrics.json")
    print("sampled: sys_cpu_percent, sys_rss_mb (one point per heartbeat)")
    print(f"see it with: vmn exp show {APP_NAME} {run.id}")


if __name__ == "__main__":
    main()
