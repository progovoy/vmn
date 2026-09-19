"""Tests for the optional release stages in ci/pipeline.py.

Run with the muster venv (it has debug_router + pytest):
    .mtd/muster_venv/bin/pytest ci/test_pipeline.py -q

Skipped elsewhere (the Docker test suite has no debug_router).
"""

import importlib.util
import os

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
    and mirrors ctx.skip (raises StageSkipped, capturing the reason)."""

    def __init__(self, **params):
        self.params = params
        self.calls = []
        self.skipped = None

    def run(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))

    def skip(self, reason=""):
        self.skipped = reason
        raise StageSkipped(reason)


@pytest.fixture(scope="module")
def mod():
    return _load_pipeline_module()


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
    ctx = FakeCtx()
    with pytest.raises(StageSkipped):
        mod.stamp(ctx)
    assert ctx.calls == []
    assert ctx.skipped is not None


def test_stamp_rejects_unknown_mode(mod):
    ctx = FakeCtx(stamp="hotfix")
    with pytest.raises(RuntimeError):
        mod.stamp(ctx)
    assert ctx.calls == []


# ---- build -------------------------------------------------------------


def test_build_runs_make_build_when_enabled(mod):
    ctx = FakeCtx(build="1")
    mod.build(ctx)
    assert ctx.calls == [(["make", "_build"], {})]


def test_build_skips_when_param_absent(mod):
    ctx = FakeCtx()
    with pytest.raises(StageSkipped):
        mod.build(ctx)
    assert ctx.calls == []
    assert ctx.skipped is not None


def test_build_passes_prerelease_template_for_rc(mod):
    # `make rc` relies on _rc's $(eval) surviving into _build within one make
    # process; the pipeline splits stamp/build across processes, so the rc
    # template must be passed to _build explicitly or the wheel drops the -rc.N.
    ctx = FakeCtx(build="1", stamp="rc")
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
    ctx = FakeCtx(build="1", stamp="patch")
    mod.build(ctx)
    assert ctx.calls == [(["make", "_build"], {})]


# ---- upload ------------------------------------------------------------


def test_upload_runs_make_upload_when_enabled(mod):
    ctx = FakeCtx(upload="true")
    mod.upload(ctx)
    assert ctx.calls == [(["make", "upload"], {})]


def test_upload_skips_when_param_absent(mod):
    ctx = FakeCtx()
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
