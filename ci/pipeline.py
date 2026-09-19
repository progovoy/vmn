"""Local CI pipeline for vmn — runs tests daily in a dedicated venv.

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
VENV_DIR = os.path.join(REPO_ROOT, '.mtd', 'ci_venv')
PYTHON = os.path.join(VENV_DIR, 'bin', 'python')
PIP = os.path.join(VENV_DIR, 'bin', 'pip')


def _run(cmd, label, cwd=REPO_ROOT, env=None):
    result = subprocess.run(cmd, cwd=cwd, env=env,
                            capture_output=True, text=True)
    if result.returncode != 0:
        msg = result.stdout + result.stderr
        raise RuntimeError(f'{label} failed (exit {result.returncode}):\n{msg}')
    return result


def _venv_env():
    env = dict(os.environ)
    env['VIRTUAL_ENV'] = VENV_DIR
    env['PATH'] = os.path.join(VENV_DIR, 'bin') + os.pathsep + env['PATH']
    env.pop('PYTHONPATH', None)
    return env


def _write(ctx, rel, text):
    dest = os.path.join(ctx.workspace, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'w') as fh:
        fh.write(text)


@stage(outputs=['reports/venv.txt'], deterministic=True)
def setup_venv(ctx):
    if not os.path.isfile(PYTHON):
        _run([sys.executable, '-m', 'venv', '--clear', VENV_DIR],
             'venv creation')
    _run([PIP, 'install', '--quiet', '-r',
          os.path.join(REPO_ROOT, 'tests', 'requirements.txt')],
         'install requirements')
    _run([PIP, 'install', '--quiet', '-r',
          os.path.join(REPO_ROOT, 'tests', 'test_requirements.txt')],
         'install test requirements')
    _run([PIP, 'install', '--quiet', '-e', REPO_ROOT],
         'install vmn editable')
    result = _run([PYTHON, '-c', 'import version_stamp; print("ok")'],
                  'verify import')
    _write(ctx, 'reports/venv.txt', f'venv ready: {VENV_DIR}\n')


@stage(inputs=['reports/venv.txt'], outputs=['reports/lint.txt'])
def lint(ctx):
    env = _venv_env()
    result = subprocess.run(
        [PYTHON, '-m', 'ruff', 'check', os.path.join(REPO_ROOT, 'version_stamp'),
         '--output-format', 'concise'],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    _write(ctx, 'reports/lint.txt',
           result.stdout + f'\nexit code: {result.returncode}\n')


@stage(inputs=['reports/venv.txt'], outputs=['reports/tests.xml', 'reports/tests.txt'])
def run_tests(ctx):
    env = _venv_env()
    xml_path = os.path.join(ctx.workspace, 'reports', 'tests.xml')
    html_path = os.path.join(ctx.workspace, 'reports', 'tests.html')
    os.makedirs(os.path.join(ctx.workspace, 'reports'), exist_ok=True)
    cmd = [
        PYTHON, '-m', 'pytest',
        os.path.join(REPO_ROOT, 'tests'),
        '-n', '29',
        f'--junitxml={xml_path}',
        f'--html={html_path}', '--self-contained-html',
        '-vv',
    ]
    result = subprocess.run(cmd, cwd=REPO_ROOT, env=env,
                            capture_output=True, text=True)
    lines = result.stdout.strip().split('\n')
    summary = '\n'.join(lines[-10:]) + f'\nexit code: {result.returncode}\n'
    _write(ctx, 'reports/tests.txt', summary)
    if result.returncode not in (0, 1):
        raise RuntimeError(
            f'pytest crashed (exit {result.returncode}):\n'
            + result.stdout[-2000:] + '\n' + result.stderr[-2000:])


@stage(inputs=['reports/venv.txt'], outputs=['reports/typecheck.txt'])
def typecheck(ctx):
    env = _venv_env()
    result = subprocess.run(
        [PYTHON, '-m', 'mypy', os.path.join(REPO_ROOT, 'version_stamp'),
         '--ignore-missing-imports'],
        cwd=REPO_ROOT, env=env, capture_output=True, text=True)
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
