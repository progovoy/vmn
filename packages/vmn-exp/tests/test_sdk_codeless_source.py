"""codeless_source: the RecordSource of a run that records no code, chosen
only by ``start_run(code=False)`` / ``VMN_EXP_CODE=none`` (plan 38 A10)."""
import contextlib

import pytest

from memory_storage import MemoryStorage
from vmn_exp.core.writer import create_run as record_run
from vmn_exp.sdk.codeless import CODELESS_KEY, CODELESS_VERSTR, CodelessIO, codeless_source
from vmn_exp.sdk.create import CHECKOUT, CODELESS, SNAPSHOT, source_kind

NOW = "2026-11-11T10:00:00.000000Z"


class LogStorage(MemoryStorage):
    """MemoryStorage that keeps each run's log entries too."""

    def __init__(self):
        super().__init__()
        self.logs = {}

    def append_log_entry(self, app_name, verstr, stream, entry):
        self.logs.setdefault((app_name, verstr), []).append(entry)


class FakeIO:
    """The collaborators codeless_source reaches for, recorded."""

    def __init__(self, storage=None, launcher=None):
        self.storage = storage
        self.launcher = launcher  # the parent VMN_EXPERIMENT_ID names
        self.parent_calls = []

    def default_storage(self):
        if self.storage is None:
            raise ValueError("No experiment store for a run without a git checkout")
        return self.storage

    def pick_parent(self, storage, app_name, parent, nested):
        self.parent_calls.append((storage, app_name, parent, nested))
        return parent or self.launcher

    def io(self):
        return CodelessIO(self.default_storage, self.pick_parent,
                          lambda capture: {"python": "3.12"} if capture else None,
                          lambda: NOW, contextlib.nullcontext)


def _source(fake, app_name="app", env=None, storage=None, parent=None, capture_env=None):
    return codeless_source(app_name, parent, False, storage, capture_env, env or {}, fake.io())


def test_requires_an_explicit_app_name():
    with pytest.raises(ValueError, match="VMN_APP_NAME"):
        _source(FakeIO(MemoryStorage()), app_name=None)
    source = _source(FakeIO(MemoryStorage()), app_name=None, env={"VMN_APP_NAME": "from_env"})
    assert source.app_name == "from_env"


def test_requires_an_explicit_store():
    with pytest.raises(ValueError, match="No experiment store"):
        _source(FakeIO(storage=None))
    given = MemoryStorage()
    assert _source(FakeIO(storage=None), storage=given).storage is given


def test_template_has_no_base_commit_and_marks_code_none():
    source = _source(FakeIO(MemoryStorage()))
    assert source.code_verstr == CODELESS_VERSTR
    assert source.template[CODELESS_KEY] is True
    assert source.template["timestamp"] == NOW
    for key in ("base_commit", "branch", "remote", "code"):
        assert key not in source.template
    assert source.features is None and source.exp_conf == {}


def test_two_codeless_runs_get_distinct_verstrs():
    source = _source(FakeIO(LogStorage()), capture_env=True)
    made = [
        record_run(source.storage, source.app_name, source.code_verstr, source.template, {},
                   parent=source.parent, env=source.env)
        for _ in range(2)
    ]
    assert made == [CODELESS_VERSTR, f"{CODELESS_VERSTR}.r2"]
    meta = source.storage.metadata[("app", made[1])]
    assert meta[CODELESS_KEY] is True and meta["code_verstr"] == CODELESS_VERSTR


def test_record_source_never_goes_codeless_without_the_opt_in():
    assert source_kind(None, {}) == CHECKOUT
    assert source_kind(True, {"VMN_EXP_CODE": "none"}) == CHECKOUT
    assert source_kind(False, {}) == CODELESS
    assert source_kind(None, {"VMN_EXP_CODE": "none"}) == CODELESS
    assert source_kind(False, {"VMN_SNAPSHOT_METADATA": "/app/meta.yml"}) == SNAPSHOT
    with pytest.raises(ValueError, match="VMN_EXP_CODE"):
        source_kind(None, {"VMN_EXP_CODE": "off"})


def test_codeless_run_nests_under_vmn_experiment_id_like_any_run():
    fake = FakeIO(MemoryStorage(), launcher="0.0.0-nocode")
    source = _source(fake)
    assert source.parent == "0.0.0-nocode"
    assert fake.parent_calls == [(fake.storage, "app", None, False)]


def test_readers_refuse_a_codeless_run_with_no_code_snapshot():
    from vmn_exp.core.provenance import no_code_reason
    from vmn_exp.core.rerun import rerun_blocker

    meta = dict(_source(FakeIO(MemoryStorage())).template, verstr=CODELESS_VERSTR)
    assert "no code snapshot" in no_code_reason(meta)
    assert "code=False" in no_code_reason(meta)
    assert rerun_blocker(meta) == no_code_reason(meta)


def test_show_marks_code_none():
    from vmn_exp.cli.views import base_line

    assert base_line({CODELESS_KEY: True}) == "Code:      none (recorded with code=False)"
    assert base_line({"base_version": "0.0.1", "base_commit": "abc1234ff"}) == (
        "Base:      0.0.1 (abc1234)")
