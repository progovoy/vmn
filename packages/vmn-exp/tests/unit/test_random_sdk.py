"""Attempt, report and comment ids come from the Random their caller's root
hands down, never from ``secrets``/``uuid``/``os.urandom`` directly (plan 44
G13). Formats and lengths stay as they were."""
import base64
import inspect
import re

import pytest

from fakes.host import FakeHost
from fakes.random import FakeRandom
from vmn_exp.core import run_finish
from vmn_exp.core.real_io import RealRandom
from vmn_exp.core.state_cas import new_attempt_id
from vmn_exp.reports import comments, store
from vmn_exp.sdk.run import Run

BASE32 = "abcdefghijklmnopqrstuvwxyz234567"


@pytest.mark.parametrize("taker", [Run, run_finish.finish_run, run_finish.final_state,
                                   new_attempt_id, store.create, comments.add])
def test_id_takers_have_no_real_random_default(taker):
    assert inspect.signature(taker).parameters["random"].default is inspect.Parameter.empty


def test_attempt_id_is_12_hex_chars_from_random():
    assert new_attempt_id(FakeRandom()) == FakeRandom().token_hex(6)
    assert re.fullmatch(r"[0-9a-f]{12}", new_attempt_id(RealRandom()))


def test_report_id_is_r_plus_12_base32_chars():
    expected = base64.b32encode(FakeRandom().token_bytes(10)).decode().lower()[-12:]

    assert store.new_rid(FakeRandom()) == "r" + expected
    assert re.fullmatch(f"r[{BASE32}]{{12}}", store.new_rid(RealRandom()))


def test_comment_id_keeps_its_prefix_and_length():
    expected = base64.b32encode(FakeRandom().token_bytes(10)).decode().lower()

    assert comments.new_comment_id(FakeRandom()) == "c" + expected
    assert re.fullmatch(f"c[{BASE32}]{{16}}", comments.new_comment_id(RealRandom()))


def test_a_runs_initial_attempt_comes_from_random():
    state = Run._initial_state(60, None, FakeHost(), FakeRandom(), {})

    assert state["attempt"] == FakeRandom().token_hex(6)


def test_a_final_state_attempt_comes_from_random():
    state = run_finish.final_state({"state": "running"}, 0, random=FakeRandom())

    assert state["attempt"] == FakeRandom().token_hex(6)
