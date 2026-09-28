#!/usr/bin/env python3
"""The workload ``vmn-exp run`` supervises for a uiload ``killed`` job.

Writes ``key=value`` metric lines (plus ``probe_ts``) to ``$VMN_METRICS_FILE``
each step and a ``started`` event naming ``$VMN_EXPERIMENT_ID``. It never ends
on its own before ``--steps``; the driver SIGTERMs the ``vmn-exp run`` parent,
which forwards the signal here and records the run as exit 143.
"""
import argparse
import os
import random
import time

from worker import EventLog, metric_values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--steps", type=int, default=100000)
    parser.add_argument("--step-sleep-sec", type=float, default=0.05)
    parser.add_argument("--metric-keys", default="loss,acc")
    args = parser.parse_args()

    EventLog(args.run_dir).emit(
        args.job_id, "started", verstr=os.environ.get("VMN_EXPERIMENT_ID")
    )
    keys = args.metric_keys.split(",")
    rng = random.Random(args.job_id)
    with open(os.environ["VMN_METRICS_FILE"], "a") as out:
        for step in range(args.steps):
            values = metric_values(keys, step, args.steps, rng)
            out.write("".join(f"{k}={v}\n" for k, v in values.items()))
            out.flush()
            time.sleep(args.step_sleep_sec)


if __name__ == "__main__":
    main()
