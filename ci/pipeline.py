"""Local CI pipeline for vmn — runs tests daily in a dedicated venv.

``workspace=".."`` anchors every run to the repo root (this file lives in
``ci/``): muster resolves a relative pipeline workspace against the pipeline
file, so the run tests the checked-out repo whether it's launched from the CLI,
the UI trigger, or the daily schedule — not an empty per-run scratch dir.

The venv is built by muster from each stage's ``requires`` (see
substrate/envs.py): declared reqs files + vmn installed editable. muster
content-addresses the venv by the reqs files' contents (under ``.mtd/envs``), so
all stages share one venv, it persists across runs, and it rebuilds only when a
requirements file changes; concurrent builders are serialized by muster's build
lock, so the three stages run in parallel.

Each stage runs its tool with ``ctx.run`` (bare names resolve via the venv's
bin on PATH, cwd is the workspace = repo root) which captures the output into a
per-stage card shown in the UI.

An optional release lane (stamp -> build -> upload) runs only when its run param
is set, so the daily run stays test-only. See "release lane" below.

Launch manually:
    muster run ci/pipeline.py --cache-dir .mtd/cache

Cut a release (each param is independent; combine as needed):
    muster run ci/pipeline.py --cache-dir .mtd/cache \
        --param stamp=patch --param build=1 --param upload=1

Or start the server (./ci/start.sh) and let the daily schedule fire it.
UI at http://localhost:8000 (no auth needed).
"""

from debug_router.pipeline import Pipeline, stage

# muster builds/reuses one venv from this spec (cwd is the repo, so ``-e .`` and
# the relative reqs paths resolve here). Stages declaring it run inside that venv.
REQUIRES = [
    "-r",
    "tests/requirements.txt",
    "-r",
    "tests/test_requirements.txt",
    "-e",
    ".",
]


@stage(requires=REQUIRES)
def lint(ctx):
    # report-only: warnings don't fail the pipeline.
    ctx.run(
        ["ruff", "check", "version_stamp", "--output-format", "concise"],
        check=False,
    )


@stage(requires=REQUIRES, outputs=["reports/tests.xml", "reports/tests.html"])
def run_tests(ctx):
    result = ctx.run(
        [
            "pytest",
            "tests",
            "-n",
            "29",
            "--junitxml=reports/tests.xml",
            "--html=reports/tests.html",
            "--self-contained-html",
            "-vv",
        ],
        check=False,
    )
    # exit 1 = tests failed (keep the report); >1 = pytest itself crashed.
    if result.returncode not in (0, 1):
        raise RuntimeError(f"pytest crashed (exit {result.returncode})")


@stage(requires=REQUIRES)
def typecheck(ctx):
    # report-only.
    ctx.run(["mypy", "version_stamp", "--ignore-missing-imports"], check=False)


# --- optional release lane -------------------------------------------------
# stamp -> build -> upload run only when their run param is set (skip otherwise),
# after run_tests so a release never ships on a crashed test run. They reuse the
# Makefile targets and are side-effecting, so they stay non-deterministic (never
# cached). Trigger with e.g.:
#   muster run ci/pipeline.py --param stamp=patch --param build=1 --param upload=1
_STAMP_MODES = {"major", "minor", "patch", "rc"}
_TRUTHY = {"1", "true", "yes", "on"}
# Makefile `_rc` sets this via $(eval), which only survives into `_build` within
# one make process. stamp and build are separate `make` calls here, so pass it
# through explicitly for rc — else the wheel embeds 0.10.2 instead of 0.10.2-rc.N.
_RC_BUILD_ARG = "EXTRA_SHOW_ARGS=--template [{major}][.{minor}][.{patch}][{prerelease}]"


def _param(ctx, key):
    return str(ctx.params.get(key, "")).strip().lower()


@stage(requires=REQUIRES, after=["run_tests"])
def stamp(ctx):
    mode = _param(ctx, "stamp")
    if not mode:
        ctx.skip("no stamp requested")
    if mode not in _STAMP_MODES:
        raise RuntimeError(
            f"stamp param must be one of {sorted(_STAMP_MODES)}, got {mode!r}"
        )
    ctx.run(["make", f"_{mode}"])


@stage(requires=REQUIRES, after=["stamp"])
def build(ctx):
    if _param(ctx, "build") not in _TRUTHY:
        ctx.skip("build not requested")
    cmd = ["make", "_build"]
    if _param(ctx, "stamp") == "rc":
        cmd.append(_RC_BUILD_ARG)
    ctx.run(cmd)


@stage(requires=REQUIRES, after=["build"])
def upload(ctx):
    if _param(ctx, "upload") not in _TRUTHY:
        ctx.skip("upload not requested")
    ctx.run(["make", "upload"])


pipeline = Pipeline(
    "vmn-ci",
    stages=[lint, run_tests, typecheck, stamp, build, upload],
    workspace="..",
)
