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

from debug_router.pipeline import StageSkipped  # noqa: E402

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


def test_stamp_skips_when_param_absent(mod):
    # An optional param with no default is omitted by muster when unset, so
    # ctx.params.get("stamp") is None and the stage skips.
    ctx = FakeCtx()
    with pytest.raises(StageSkipped):
        mod.stamp(ctx)
    assert ctx.calls == []
    assert ctx.skipped is not None


# An unknown stamp mode is rejected by muster (against the declared choices)
# before the stage runs, so the stage no longer validates it — see
# test_pipeline_declares_release_params for the declared choices.


# ---- build -------------------------------------------------------------


def test_build_runs_make_build_when_enabled(mod):
    # muster coerces the declared bool, so the stage sees real True.
    ctx = FakeCtx(build=True)
    mod.build(ctx)
    assert ctx.calls == [(["make", "_build"], {})]


def test_build_skips_when_disabled(mod):
    # build defaults to False, so muster always delivers it as a real bool.
    ctx = FakeCtx(build=False)
    with pytest.raises(StageSkipped):
        mod.build(ctx)
    assert ctx.calls == []
    assert ctx.skipped is not None


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


def test_upload_skips_when_disabled(mod):
    ctx = FakeCtx(upload=False)
    with pytest.raises(StageSkipped):
        mod.upload(ctx)
    assert ctx.calls == []
    assert ctx.skipped is not None


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
