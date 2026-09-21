"""Tests for the optional release stages in ci/pipeline.py.

Run with the muster venv (it has debug_router + pytest):
    .mtd/muster_venv/bin/pytest ci/test_pipeline.py -q

Skipped elsewhere (the Docker test suite has no debug_router).
"""

import importlib.util
import os
import types

import pytest

pytest.importorskip("debug_router")

from debug_router.pipeline import StageSkipped, conditions  # noqa: E402
from debug_router.pipeline.conditions import ConditionContext  # noqa: E402

HERE = os.path.dirname(__file__)


def _load_pipeline_module():
    spec = importlib.util.spec_from_file_location(
        "vmn_ci_pipeline", os.path.join(HERE, "pipeline.py")
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class FakeCtx:
    """Minimal StageContext stand-in: records ctx.run calls, carries params,
    mirrors ctx.skip (raises StageSkipped) and ctx.run's check=True (a nonzero
    exit raises), and returns a CompletedProcess-like result whose exit code the
    test controls."""

    def __init__(self, run_returncode=0, **params):
        self.params = params
        self.calls = []
        self.skipped = None
        self.run_returncode = run_returncode

    def run(self, cmd, *, check=True, **kwargs):
        self.calls.append((cmd, kwargs))
        # Mirror StageContext.run: under check=True a nonzero exit raises (the
        # real card is written first), so a stage that omits check=False fails.
        if check and self.run_returncode != 0:
            raise RuntimeError(f"command failed (exit {self.run_returncode})")
        return types.SimpleNamespace(returncode=self.run_returncode)

    def skip(self, reason=""):
        self.skipped = reason
        raise StageSkipped(reason)


@pytest.fixture(scope="module")
def mod():
    return _load_pipeline_module()


# ---- run_tests ---------------------------------------------------------


def test_run_tests_passes_on_exit_zero(mod):
    ctx = FakeCtx(run_returncode=0)
    mod.run_tests(ctx)  # green: no exception
    assert ctx.calls and ctx.calls[0][0][0] == "pytest"


def test_run_tests_fails_on_test_failure(mod):
    # exit 1 = at least one test failed. The stage must go RED (raise), not
    # report green while the suite is broken.
    ctx = FakeCtx(run_returncode=1)
    with pytest.raises(RuntimeError):
        mod.run_tests(ctx)


def test_run_tests_fails_on_pytest_crash(mod):
    # exit >1 = pytest itself crashed — also RED.
    ctx = FakeCtx(run_returncode=2)
    with pytest.raises(RuntimeError):
        mod.run_tests(ctx)


# ---- lint --------------------------------------------------------------


def test_lint_passes_on_exit_zero(mod):
    ctx = FakeCtx(run_returncode=0)
    mod.lint(ctx)  # green: no exception
    assert ctx.calls and ctx.calls[0][0][0] == "ruff"


def test_lint_fails_on_ruff_error(mod):
    # exit 1 = ruff found lint errors. The stage must go RED (raise) so the
    # pipeline fails, rather than reporting green on a broken lint.
    ctx = FakeCtx(run_returncode=1)
    with pytest.raises(RuntimeError):
        mod.lint(ctx)


# ---- stamp -------------------------------------------------------------


@pytest.mark.parametrize(
    "mode,target",
    [
        ("patch", "_patch"),
        ("minor", "_minor"),
        ("major", "_major"),
        ("rc", "_rc"),
    ],
)
def test_stamp_runs_matching_make_target(mod, mode, target):
    ctx = FakeCtx(stamp=mode)
    mod.stamp(ctx)
    assert ctx.calls == [(["make", target], {})]


# Whether stamp runs at all is now a `when=` condition, not a ctx.skip inside the
# body — see the conditional-release-lane tests below.

# An unknown stamp mode is rejected by muster (against the declared choices)
# before the stage runs, so the stage no longer validates it — see
# test_pipeline_declares_release_params for the declared choices.


# ---- build -------------------------------------------------------------


def test_build_runs_make_build_when_enabled(mod):
    # muster coerces the declared bool, so the stage sees real True.
    ctx = FakeCtx(build=True)
    mod.build(ctx)
    assert ctx.calls == [(["make", "_build"], {})]


def test_build_passes_prerelease_template_for_rc(mod):
    # `make rc` relies on _rc's $(eval) surviving into _build within one make
    # process; the pipeline splits stamp/build across processes, so the rc
    # template must be passed to _build explicitly or the wheel drops the -rc.N.
    ctx = FakeCtx(build=True, stamp="rc")
    mod.build(ctx)
    assert ctx.calls == [
        (
            [
                "make",
                "_build",
                "EXTRA_SHOW_ARGS=--template "
                "[{major}][.{minor}][.{patch}][{prerelease}]",
            ],
            {},
        )
    ]


def test_build_no_template_for_non_rc_stamp(mod):
    ctx = FakeCtx(build=True, stamp="patch")
    mod.build(ctx)
    assert ctx.calls == [(["make", "_build"], {})]


# ---- upload ------------------------------------------------------------


def test_upload_runs_make_upload_when_enabled(mod):
    ctx = FakeCtx(upload=True)
    mod.upload(ctx)
    assert ctx.calls == [(["make", "upload"], {})]


# ---- conditional release lane ------------------------------------------
# The release stages declare `when=`, so muster decides before the stage takes a
# slot: an unrequested stage never resolves the venv or starts a subprocess, and
# `muster inspect` shows it as "would skip" without running anything.


def _cond(**params):
    return ConditionContext(params=params)


@pytest.mark.parametrize("name", ["stamp", "build", "upload"])
def test_release_stage_is_not_scheduled_without_its_param(mod, name):
    assert conditions.should_run(mod.pipeline.get_stage(name), _cond()) is False


@pytest.mark.parametrize(
    "name,params",
    [
        ("stamp", {"stamp": "patch"}),
        ("build", {"build": True}),
        ("upload", {"upload": True}),
    ],
)
def test_release_stage_is_scheduled_when_its_param_is_set(mod, name, params):
    spec = mod.pipeline.get_stage(name)
    # Assert the condition exists, or this passes vacuously: an unconditional
    # stage always runs.
    assert conditions.is_conditional(spec)
    assert conditions.should_run(spec, _cond(**params)) is True


def test_build_is_independent_of_stamp(mod):
    # `--param build=1` alone still builds: a when=-skipped stage satisfies the
    # default all_success trigger in muster, so skipping stamp doesn't cascade.
    ctx = _cond(build=True)
    assert conditions.should_run(mod.pipeline.get_stage("build"), ctx) is True
    assert conditions.should_run(mod.pipeline.get_stage("stamp"), ctx) is False


# ---- caching -----------------------------------------------------------


def test_run_tests_is_cached_on_the_sources_it_reads(mod):
    # The daily run re-ran the whole suite even when nothing changed. Declaring
    # the trees the tests actually read makes the stage content-addressable, so
    # an unchanged repo restores the JUnit/HTML reports instead of re-running.
    spec = mod.pipeline.get_stage("run_tests")
    assert spec.deterministic is True
    assert set(spec.inputs) == {"version_stamp", "tests", "setup.py"}
    assert spec.outputs  # a cache hit must restore the reports the UI renders


# ---- wiring ------------------------------------------------------------


def test_release_stages_run_after_tests_in_order(mod):
    order = [s.name for s in mod.pipeline.topological_order()]
    for name in ("run_tests", "stamp", "build", "upload"):
        assert name in order, f"{name} missing from pipeline"
    assert order.index("run_tests") < order.index("stamp")
    assert order.index("stamp") < order.index("build")
    assert order.index("build") < order.index("upload")


def test_release_stages_are_not_cached(mod):
    # Side-effecting stages must never be content-address cached.
    for name in ("stamp", "build", "upload"):
        assert mod.pipeline.get_stage(name).deterministic is False


def test_pipeline_declares_release_params(mod):
    # The release lane's params are declared so the trigger UI can render them
    # as typed fields (a stamp-mode dropdown, build/upload checkboxes).
    spec = {p.name: p for p in mod.pipeline.param_spec}
    assert set(spec) == {"stamp", "build", "upload"}
    assert spec["stamp"].choices == ["major", "minor", "patch", "rc"]
    assert not spec["stamp"].required  # unset = skip
    assert spec["build"].type == "bool"
    assert spec["upload"].type == "bool"
