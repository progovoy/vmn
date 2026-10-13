"""Full uiload profile run: ``smoke`` by default, another with
``VMN_UILOAD_PROFILE=load``. Serial (run_pytest.sh's one-process pass, never
under xdist): it owns the machine for the profile's duration.

    VMN_UILOAD_PROFILE=load python -m pytest -s packages/vmn-exp/tests/test_uiload_profile.py
"""
import json
import os

import pytest

PROFILE = os.environ.get("VMN_UILOAD_PROFILE", "smoke")
pytestmark = pytest.mark.serial


def test_profile_meets_budgets_and_statuses_agree(tmp_path):
    from uiload import driver, scenario

    report = driver.run_check(scenario.get_profile(PROFILE), str(tmp_path),
                              browser=os.environ.get("VMN_UILOAD_BROWSER", "1") != "0")
    print(json.dumps(report, indent=2, default=str))
    assert driver.failures(report) == []
