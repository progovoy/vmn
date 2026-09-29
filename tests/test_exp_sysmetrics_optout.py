#!/usr/bin/env python3
"""System metrics are on by default; each opt-out switches them off.

Precedence mirrors env capture: CLI flag / explicit ``False`` > the
``VMN_SYSTEM_METRICS`` env var > conf ``experiment.system_metrics`` > on.
"""
import os
import re
import time

import pytest
import yaml

from vmn_exp.sdk import start_run, sysmetrics
from vmn_exp.sdk.ranks import NoOpRun
from helpers import _PY, _bootstrap, _experiment, _storage, extract_dev_verstr

_FAKE_SAMPLE = {"sys_cpu_percent": 12.5, "sys_rss_mb": 64.0}
_OPT_OUT_VALUES = ("0", "false", "no", "off")


@pytest.fixture
def built(monkeypatch):
    """Fake collector; records every build so a test can assert none happened."""
    calls = []

    def _build(pid=None):
        calls.append(pid)
        return lambda: dict(_FAKE_SAMPLE)

    monkeypatch.setattr(sysmetrics, "build_collector", _build)
    monkeypatch.delenv(sysmetrics.SYSTEM_METRICS_ENV, raising=False)
    return calls


def _sys_entries(app_layout, verstr):
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    return [
        e
        for e in log
        if e.get("type") == "metrics"
        and any(k in sysmetrics.SYS_METRIC_NAMES for k in e.get("values") or {})
    ]


def _sdk_run(app_layout, **kwargs):
    with start_run(app_layout.app_name, heartbeat_interval_sec=0.1, **kwargs) as run:
        time.sleep(0.4)
    return run.id


def _cli_run(app_layout, capfd, *flags):
    capfd.readouterr()
    assert (
        _experiment(
            app_layout.app_name,
            action="run",
            run_cmd=[_PY, "-c", "import time; time.sleep(2.4)"],
            extra_args=["--heartbeat-interval", "1", *flags],
        )
        == 0
    )
    return extract_dev_verstr(capfd.readouterr().out)


def _conf_system_metrics(app_layout, value):
    conf_path = os.path.join(
        app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml"
    )
    with open(conf_path) as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("conf", {}).setdefault("experiment", {})["system_metrics"] = value
    with open(conf_path, "w") as f:
        yaml.dump(data, f)


# ---------------------------------------------------------------------------
# the decision itself
# ---------------------------------------------------------------------------


def test_enabled_by_default(monkeypatch):
    monkeypatch.delenv(sysmetrics.SYSTEM_METRICS_ENV, raising=False)
    assert sysmetrics.enabled(None) is True
    assert sysmetrics.enabled(None, {}) is True


@pytest.mark.parametrize("value", _OPT_OUT_VALUES)
def test_env_var_opts_out(monkeypatch, value):
    monkeypatch.setenv("VMN_SYSTEM_METRICS", value)
    assert sysmetrics.enabled(None) is False
    # An explicit True overrides conf, never the env var (as with capture_env).
    assert sysmetrics.enabled(True, {"system_metrics": True}) is False


def test_conf_opts_out_and_explicit_true_overrides_it(monkeypatch):
    monkeypatch.delenv(sysmetrics.SYSTEM_METRICS_ENV, raising=False)
    assert sysmetrics.enabled(None, {"system_metrics": False}) is False
    assert sysmetrics.enabled(True, {"system_metrics": False}) is True


def test_explicit_false_beats_everything(monkeypatch):
    monkeypatch.setenv("VMN_SYSTEM_METRICS", "1")
    assert sysmetrics.enabled(False, {"system_metrics": True}) is False


# ---------------------------------------------------------------------------
# SDK opt-outs
# ---------------------------------------------------------------------------


def test_sdk_kwarg_false_records_nothing(app_layout, built):
    _bootstrap(app_layout)
    verstr = _sdk_run(app_layout, system_metrics=False)
    assert _sys_entries(app_layout, verstr) == []
    assert built == []


def test_sdk_env_var_records_nothing(app_layout, built, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv("VMN_SYSTEM_METRICS", "off")
    verstr = _sdk_run(app_layout)
    assert _sys_entries(app_layout, verstr) == []


def test_sdk_conf_records_nothing(app_layout, built):
    _bootstrap(app_layout)
    _conf_system_metrics(app_layout, False)
    verstr = _sdk_run(app_layout)
    assert _sys_entries(app_layout, verstr) == []


def test_sdk_explicit_true_overrides_conf(app_layout, built):
    _bootstrap(app_layout)
    _conf_system_metrics(app_layout, False)
    verstr = _sdk_run(app_layout, system_metrics=True)
    assert _sys_entries(app_layout, verstr)


def test_secondary_rank_stays_a_noop(app_layout, built, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv("RANK", "1")
    run = start_run(app_layout.app_name, heartbeat_interval_sec=0.1)
    assert isinstance(run, NoOpRun)
    time.sleep(0.3)
    run.finish()
    assert built == []


# ---------------------------------------------------------------------------
# CLI opt-outs
# ---------------------------------------------------------------------------


def test_cli_flag_records_nothing(app_layout, capfd, built):
    _bootstrap(app_layout)
    verstr = _cli_run(app_layout, capfd, "--no-system-metrics")
    assert _sys_entries(app_layout, verstr) == []
    assert built == []


def test_cli_env_var_records_nothing(app_layout, capfd, built, monkeypatch):
    _bootstrap(app_layout)
    monkeypatch.setenv("VMN_SYSTEM_METRICS", "0")
    verstr = _cli_run(app_layout, capfd)
    assert _sys_entries(app_layout, verstr) == []


def test_cli_conf_records_nothing(app_layout, capfd, built):
    _bootstrap(app_layout)
    _conf_system_metrics(app_layout, False)
    verstr = _cli_run(app_layout, capfd)
    assert _sys_entries(app_layout, verstr) == []


def test_cli_old_opt_in_flag_is_gone(app_layout, capfd, built):
    _bootstrap(app_layout)
    with pytest.raises(SystemExit):
        _experiment(
            app_layout.app_name,
            action="run",
            run_cmd=[_PY, "-c", "pass"],
            extra_args=["--system-metrics"],
        )


# ---------------------------------------------------------------------------
# dependencies
# ---------------------------------------------------------------------------


def test_psutil_is_a_hard_dependency_and_pynvml_is_not():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "..", "packages", "vmn-exp-sdk", "pyproject.toml")
    with open(path) as f:
        text = f.read()
    deps = re.search(r"^dependencies = \[(.*?)\]", text, re.S | re.M).group(1)
    assert "psutil" in deps
    assert "pynvml" not in deps
