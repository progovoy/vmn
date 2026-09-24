"""Local CI pipeline for vmn — runs tests daily in a dedicated venv.

``workspace=".."`` anchors every run to the repo root (this file lives in
``ci/``): muster resolves a relative pipeline workspace against the pipeline
file, so the run tests the checked-out repo whether it's launched from the CLI,
the UI trigger, or the daily schedule — not an empty per-run scratch dir.

The venv is built by muster from each stage's ``requires`` (see
substrate/envs.py): the muster runtime, then the declared reqs files and vmn
installed editable. ``requires`` does NOT augment whatever the process running
muster happens to have installed — the venv starts empty, so every tool a stage
invokes has to be declared (ruff/pytest/mypy all are, in test_requirements.txt).
Because ``requires`` installs after the runtime, a pin here wins over a muster
runtime dep of the same name.

muster content-addresses the venv by the interpreter identity plus the reqs
files' contents (``.mtd/envs/cpython-<X.Y>-<digest>``), so all stages share one
venv, it persists across runs, and it rebuilds only when a requirements file or
the interpreter changes; concurrent builders are serialized by muster's build
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

The same file runs unchanged on a central server that sends each run to an
on-demand Docker worker (``ci/server.toml``): the run is pinned to the triggered
commit, so the worker tests exactly that tree (a dirty tree is refused unless
``--allow-dirty`` ships the patch). ``workspace=".."`` still resolves to the repo
root inside the worker's checkout. From a laptop:
    muster run ci/pipeline.py --runs-on docker
"""

from debug_router.pipeline import Param, Pipeline, stage

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
    # ctx.run defaults to check=True: ruff finding lint errors (exit 1) fails the
    # stage so the pipeline goes red instead of reporting green on a broken lint.
    ctx.run(["ruff", "check", "version_stamp", "--output-format", "concise"])


# deterministic=True + declared inputs make this content-addressable: the key is
# the stage's source closure, the hash of the trees below, the venv
# fingerprint (interpreter + the requirements files' contents) and the platform
# (so a macOS laptop's result is never served to Linux CI). An unchanged repo
# restores reports/ from the cache instead of re-running the suite; setup.py is an input because `-e .` decides what the tests import, and
# muster's tree hashing ignores __pycache__ so bytecode never churns the key.
@stage(
    requires=REQUIRES,
    deterministic=True,
    inputs=["version_stamp", "tests", "setup.py"],
    outputs=["reports/tests.xml", "reports/tests.html"],
)
def run_tests(ctx):
    # ctx.run defaults to check=True: it writes the output card, then fails the
    # stage on any nonzero exit — test failures (exit 1) and pytest crashes
    # (exit >1) both go red. pytest writes the JUnit/HTML report as it runs, so a
    # red stage still carries the full output.
    ctx.run(
        [
            "pytest",
            "tests",
            "-n",
            "29",
            "--junitxml=reports/tests.xml",
            "--html=reports/tests.html",
            "--self-contained-html",
            "-vv",
        ]
    )


@stage(requires=REQUIRES)
def typecheck(ctx):
    # report-only.
    ctx.run(["mypy", "version_stamp", "--ignore-missing-imports"], check=False)


# --- optional release lane -------------------------------------------------
# stamp -> build -> upload run only when their declared run param is set, after
# run_tests so a release never ships on a crashed test run. The gate is a
# `when=` condition, which muster evaluates once per run *before* the stage takes
# a slot — so an unrequested stage costs nothing (no venv, no subprocess) and
# `muster inspect` reports it as "would skip" without running anything. Each
# param stays independent: a when=-skipped stage satisfies the default
# all_success trigger, so skipping stamp does not skip build.
# muster validates and coerces the params from the declarations below (stamp
# against STAMP_MODES; build/upload to real bools) before any stage runs, so the
# stages just read ctx.params. They reuse the Makefile targets and are
# side-effecting, so they stay non-deterministic (never cached). Trigger e.g.:
#   muster run ci/pipeline.py --param stamp=patch --param build=1 --param upload=1
STAMP_MODES = ["major", "minor", "patch", "rc"]
# Makefile `_rc` sets this via $(eval), which only survives into `_build` within
# one make process. stamp and build are separate `make` calls here, so pass it
# through explicitly for rc — else the wheel embeds 0.10.2 instead of 0.10.2-rc.N.
_RC_BUILD_ARG = "EXTRA_SHOW_ARGS=--template [{major}][.{minor}][.{patch}][{prerelease}]"


@stage(
    requires=REQUIRES,
    after=["run_tests"],
    when=lambda c: bool(c.params.get("stamp")),
    params=[
        Param(
            "stamp",
            choices=STAMP_MODES,
            help="Stamp a version (make _<mode>); leave unset to skip",
        )
    ],
)
def stamp(ctx):
    ctx.run(["make", f"_{ctx.params['stamp']}"])


@stage(
    requires=REQUIRES,
    after=["stamp"],
    when=lambda c: bool(c.params.get("build")),
    params=[Param("build", default=False, help="Build the wheel (make _build)")],
)
def build(ctx):
    cmd = ["make", "_build"]
    if ctx.params.get("stamp") == "rc":
        cmd.append(_RC_BUILD_ARG)
    ctx.run(cmd)


@stage(
    requires=REQUIRES,
    after=["build"],
    when=lambda c: bool(c.params.get("upload")),
    params=[Param("upload", default=False, help="Upload the wheel (make upload)")],
)
def upload(ctx):
    ctx.run(["make", "upload"])


pipeline = Pipeline(
    "vmn-ci",
    stages=[lint, run_tests, typecheck, stamp, build, upload],
    workspace="..",
)
