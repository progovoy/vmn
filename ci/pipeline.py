"""Local CI pipeline for vmn — runs tests daily in a dedicated venv.

The venv is built by muster from each stage's ``requires`` (see
substrate/envs.py): declared reqs files + vmn installed editable. muster
content-addresses the venv by the reqs files' contents, so all four stages
share one venv and it rebuilds only when a requirements file changes.

Launch manually:
    muster run ci/pipeline.py --cache-dir .mtd/cache

Or start the server (./ci/start.sh) and let the daily schedule fire it.
UI at http://localhost:8000 (no auth needed).
"""
import os
import subprocess
import sys

from debug_router.pipeline import Pipeline, stage

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# muster builds/reuses one venv from this spec (cwd is the repo, so ``-e .`` and
# the relative reqs paths resolve here). Stages declaring it run inside that venv.
REQUIRES = ['-r', 'tests/requirements.txt',
            '-r', 'tests/test_requirements.txt', '-e', '.']


def _write(ctx, rel, text):
    dest = os.path.join(ctx.workspace, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'w') as fh:
        fh.write(text)


@stage(requires=REQUIRES, outputs=['reports/venv.txt'])
def setup_venv(ctx):
    result = subprocess.run([sys.executable, '-c',
                             'import version_stamp; print("ok")'],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError('venv verify failed:\n'
                           + result.stdout + result.stderr)
    _write(ctx, 'reports/venv.txt', 'venv ready\n')


@stage(requires=REQUIRES, inputs=['reports/venv.txt'], outputs=['reports/lint.txt'])
def lint(ctx):
    result = subprocess.run(
        [sys.executable, '-m', 'ruff', 'check',
         os.path.join(REPO_ROOT, 'version_stamp'), '--output-format', 'concise'],
        capture_output=True, text=True)
    _write(ctx, 'reports/lint.txt',
           result.stdout + f'\nexit code: {result.returncode}\n')


@stage(requires=REQUIRES, inputs=['reports/venv.txt'],
       outputs=['reports/tests.xml', 'reports/tests.txt'])
def run_tests(ctx):
    xml_path = os.path.join(ctx.workspace, 'reports', 'tests.xml')
    html_path = os.path.join(ctx.workspace, 'reports', 'tests.html')
    os.makedirs(os.path.join(ctx.workspace, 'reports'), exist_ok=True)
    cmd = [
        sys.executable, '-m', 'pytest',
        os.path.join(REPO_ROOT, 'tests'),
        '-n', '29',
        f'--junitxml={xml_path}',
        f'--html={html_path}', '--self-contained-html',
        '-vv',
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    lines = result.stdout.strip().split('\n')
    summary = '\n'.join(lines[-10:]) + f'\nexit code: {result.returncode}\n'
    _write(ctx, 'reports/tests.txt', summary)
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f'pytest crashed (exit {result.returncode}):\n'
            + result.stdout[-2000:] + '\n' + result.stderr[-2000:])


@stage(requires=REQUIRES, inputs=['reports/venv.txt'], outputs=['reports/typecheck.txt'])
def typecheck(ctx):
    result = subprocess.run(
        [sys.executable, '-m', 'mypy', os.path.join(REPO_ROOT, 'version_stamp'),
         '--ignore-missing-imports'],
        capture_output=True, text=True)
    _write(ctx, 'reports/typecheck.txt',
           result.stdout + f'\nexit code: {result.returncode}\n')


@stage(inputs=['reports/tests.txt', 'reports/lint.txt', 'reports/typecheck.txt'],
       outputs=['reports/summary.txt'])
def summary(ctx):
    parts = []
    for name in ('lint', 'typecheck', 'tests'):
        path = os.path.join(ctx.workspace, 'reports', f'{name}.txt')
        if os.path.isfile(path):
            with open(path) as fh:
                parts.append(f'=== {name} ===\n{fh.read().strip()}\n')
    _write(ctx, 'reports/summary.txt', '\n'.join(parts) + '\n')


pipeline = Pipeline('vmn-ci', stages=[setup_venv, lint, run_tests,
                                      typecheck, summary])
