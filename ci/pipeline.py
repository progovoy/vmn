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

Launch manually:
    muster run ci/pipeline.py --cache-dir .mtd/cache

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


pipeline = Pipeline("vmn-ci", stages=[lint, run_tests, typecheck], workspace="..")
