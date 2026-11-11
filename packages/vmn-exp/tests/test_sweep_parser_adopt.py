"""``vmn-exp sweep agent --no-adopt`` keeps each trial's start_run() nested
(plan 38 A12)."""
import argparse

from vmn_exp.cli.sweep.parser import add_sweep_parser


def _parse(*argv):
    parser = argparse.ArgumentParser()
    add_sweep_parser(parser.add_subparsers())
    return parser.parse_args(["sweep", "agent", "app", "sw", *argv])


def test_sweep_agent_takes_no_adopt():
    assert _parse().adopt_run is True
    assert _parse("--no-adopt").adopt_run is False
