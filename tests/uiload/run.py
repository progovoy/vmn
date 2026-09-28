#!/usr/bin/env python3
"""uiload entry point.

    python tests/uiload/run.py live  --profile smoke|load|soak [--port 8300] [--run-dir D]
    python tests/uiload/run.py check --profile smoke|load      [--no-browser] [--run-dir D]

``live`` serves the dashboard on the printed URL and churns jobs until Ctrl-C
(or the profile's duration); ``check`` runs the profile, prints the JSON report
and exits 1 on any budget violation or status mismatch.
"""
import argparse
import dataclasses
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from uiload import driver, scenario


def parse_args(argv):
    parser = argparse.ArgumentParser(description="vmn-exp ui load harness")
    parser.add_argument("mode", choices=("live", "check"))
    parser.add_argument("--profile", default="smoke", choices=sorted(scenario.PROFILES))
    parser.add_argument("--run-dir", help="where data, events and logs go (default: a new temp dir)")
    parser.add_argument("--port", type=int)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--duration", type=float, help="override the profile's duration (0 = until Ctrl-C)")
    parser.add_argument("--no-browser", action="store_true", help="check mode: skip Playwright checks")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    profile = scenario.get_profile(args.profile)
    if args.duration is not None:
        profile = dataclasses.replace(profile, duration_sec=args.duration)
    run_dir = args.run_dir or tempfile.mkdtemp(prefix=f"uiload-{profile.name}-")
    print(f"uiload: run dir {run_dir}", file=sys.stderr, flush=True)
    if args.mode == "live":
        driver.run_live(profile, run_dir, args.seed, args.port)
        return 0
    report = driver.run_check(profile, run_dir, browser=not args.no_browser,
                              rng_seed=args.seed, port=args.port)
    print(json.dumps(report, indent=2, default=str))
    problems = driver.failures(report)
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
