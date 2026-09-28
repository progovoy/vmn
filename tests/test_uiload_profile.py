"""Full uiload profile run, opt-in: ``VMN_UILOAD_PROFILE=smoke|load`` (serial,
not under xdist — it owns the machine for the profile's duration).

    VMN_UILOAD_PROFILE=smoke python -m pytest -s tests/test_uiload_profile.py
"""
import json
import os

import pytest

PROFILE = os.environ.get("VMN_UILOAD_PROFILE")
pytestmark = pytest.mark.skipif(not PROFILE, reason="set VMN_UILOAD_PROFILE to run a uiload profile")


def test_profile_meets_budgets_and_statuses_agree(tmp_path):
    from uiload import driver, scenario

    report = driver.run_check(scenario.get_profile(PROFILE), str(tmp_path),
                              browser=os.environ.get("VMN_UILOAD_BROWSER", "1") != "0")
    print(json.dumps(report, indent=2, default=str))
    assert driver.failures(report) == []
