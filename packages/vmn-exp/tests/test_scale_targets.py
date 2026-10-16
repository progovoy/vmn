"""Plan 25 §1 targets, enforced: at 100k runs (``VMN_SCALE_BENCH=1``; a few
minutes) each command, in a fresh process on the persisted index, takes at
most its target in wall time beyond a process that only imports the same
entry point (Python and the CLI import alone take ~0.25 s), and
``show``/``get_run`` add at most 50 MB to that process. The 20k variant
always runs: what the store's size adds — that time and memory minus the
same command's on a 300-run store — stays within 0.3 of the targets, so a
regression back to reading every run fails in CI. Each figure is the best of
a few runs (the machine is shared). Timed, so serial."""
import json
import os
import resource
import shutil
import subprocess
import sys
import tempfile
import time

import pytest
import scale_store
from bench_scale import SRC, checkout
from uiload import seed_records

APP = scale_store.APP
TARGET_SEC = {"show": 0.2, "get_run": 0.2, "last20": 1.0, "query": 2.0, "refresh": 0.2}
EXTRA_MB = {"show": 50, "get_run": 50}
CI_RUNS, BASE_RUNS, CI_SCALE = 20_000, 300, 0.3
CHANGED = 100
TRIES = 5
FULL = os.environ.get("VMN_SCALE_BENCH") == "1"


def _rss_mb():
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1 << 20) if sys.platform == "darwin" else peak / 1024


def child(case, work, exact, out, import_only):
    """Run *case* in this process (only import its entry point with
    *import_only* ``"1"``); write ``{extra_mb}`` beyond the import."""
    os.chdir(work)
    if case == "get_run":
        from vmn_exp.sdk.reader import get_run as run
    elif case == "refresh":
        from vmn_exp.core import index as experiment_index
        from vmn_exp.snapshot import open_storage
    else:
        from vmn_exp.cli.main import main
    before = _rss_mb()
    if import_only == "1":
        case = None
    if case == "get_run":
        run(APP, exact)
    elif case == "refresh":
        storage = open_storage(root=os.path.join(work, ".vmn", "store"), area="runs")
        assert experiment_index.shared_index(storage, APP).sync()
    elif case is not None:
        argv = {"show": ["show", APP, "-v", exact], "last20": ["list", APP, "--last", "20"],
                "query": ["list", APP, "--query", 'status = "failed"']}[case]
        sys.argv = ["vmn-exp", *argv]
        sys.stdout = open(os.devnull, "w")
        try:
            assert not main()
        except SystemExit as e:
            assert not e.code
    with open(out, "w") as f:
        json.dump({"extra_mb": _rss_mb() - before}, f)


def _measure(case, work, cache, exact, import_only=False):
    """``{wall, extra_mb}`` of *case* in a fresh process."""
    out = os.path.join(cache, "result.json")
    env = dict(os.environ, VMN_EXP_CACHE_DIR=cache, PYTHONPATH=os.pathsep.join(SRC))
    argv = [sys.executable, __file__, case, work, exact, out, "1" if import_only else "0"]
    started = time.perf_counter()
    proc = subprocess.run(argv, env=env, capture_output=True, text=True)
    wall = time.perf_counter() - started
    assert proc.returncode == 0, proc.stderr[-2000:]
    with open(out) as f:
        return dict(json.load(f), wall=wall)


def _import_wall(case, work, cache, exact):
    return min(_measure(case, work, cache, exact, True)["wall"] for _ in range(TRIES))


def _figures(runs, imported):
    """``(wall beyond the import, extra MB, wall, import wall)`` of the best *runs*."""
    wall = min(r["wall"] for r in runs)
    return wall - imported, min(r["extra_mb"] for r in runs), wall, imported


def _best(case, work, cache, exact):
    runs = [_measure(case, work, cache, exact) for _ in range(TRIES)]
    return _figures(runs, _import_wall(case, work, cache, exact))


def _private_store(root, n):
    """A checkout over a fresh *n*-run store of its own (a test writes to it),
    and the ``CHANGED`` runs spread over it a test changes. Written a day
    ago, like the cached stores: its runs are no longer live."""
    day_ago = time.time() - 86400
    scale_store.generate(root, n, now=day_ago)
    runs = os.path.join(root, ".vmn", "store", "runs", APP)
    for name in os.listdir(runs):  # the store saw the run states written then too
        state = os.path.join(runs, name, "run_state.yml")
        if os.path.exists(state):
            os.utime(state, (day_ago, day_ago))
    return checkout(root), [seed_records.verstr_of(i * (n // CHANGED), 0) for i in range(CHANGED)]


def _change(work, verstrs, note):
    from vmn_exp.snapshot import open_storage

    storage = open_storage(root=os.path.join(work, ".vmn", "store"), area="runs")
    for verstr in verstrs:
        storage.update_note(APP, verstr, note)


class Bench:
    """One store size: its checkouts, persisted indexes and measurements."""

    def __init__(self, n):
        self.n, self.exact = n, seed_records.verstr_of(n // 2, 0)
        self.root = tempfile.mkdtemp(prefix=f"vmn-scale-targets-{n}-")
        self.work = checkout(scale_store.cached(n))
        self.cache = os.path.join(self.root, "cache")
        os.mkdir(self.cache)
        _measure("last20", self.work, self.cache, self.exact)  # builds and persists the index
        self._refresh = None

    def figures(self, case):
        if case == "refresh":
            return self.refresh()
        return _best(case, self.work, self.cache, self.exact)

    def refresh(self):
        if self._refresh is None:
            work, changed = _private_store(os.path.join(self.root, "private"), self.n)
            cache = os.path.join(self.root, "private-cache")
            os.mkdir(cache)
            _measure("refresh", work, cache, self.exact)  # builds and persists the index
            runs = []
            for attempt in range(TRIES):
                _change(work, changed, f"changed since the last refresh ({attempt})")
                runs.append(_measure("refresh", work, cache, self.exact))
            imported = _import_wall("refresh", work, cache, self.exact)
            self._refresh = _figures(runs, imported)
            shutil.rmtree(work, ignore_errors=True)
        return self._refresh

    def close(self):
        shutil.rmtree(self.work, ignore_errors=True)
        shutil.rmtree(self.root, ignore_errors=True)


@pytest.fixture(scope="module")
def benches():
    made = {}

    def bench(n):
        if n not in made:
            made[n] = Bench(n)
        return made[n]

    yield bench
    for one in made.values():
        one.close()


@pytest.mark.serial
@pytest.mark.parametrize("case", sorted(TARGET_SEC))
def test_a_20k_store_adds_little_to_each_command(benches, case):
    sec, extra, wall, imported = benches(CI_RUNS).figures(case)
    base_sec, base_extra, base_wall, base_imported = benches(BASE_RUNS).figures(case)
    print(f"\n{case}: {CI_RUNS} runs {wall:.3f}s - import {imported:.3f}s = {sec:.3f}s"
          f" +{extra:.0f}MB; {BASE_RUNS} runs {base_wall:.3f}s - import {base_imported:.3f}s"
          f" = {base_sec:.3f}s +{base_extra:.0f}MB")
    assert sec - base_sec <= CI_SCALE * TARGET_SEC[case]
    if case in EXTRA_MB:
        assert extra - base_extra <= CI_SCALE * EXTRA_MB[case]


@pytest.mark.serial
@pytest.mark.skipif(not FULL, reason="the 100k targets run with VMN_SCALE_BENCH=1 (minutes)")
@pytest.mark.parametrize("case", sorted(TARGET_SEC))
def test_each_command_meets_its_target_at_100k(benches, case):
    sec, extra, wall, imported = benches(100_000).figures(case)
    print(f"\n{case}: 100k runs {wall:.3f}s - import {imported:.3f}s = {sec:.3f}s +{extra:.0f}MB")
    assert sec <= TARGET_SEC[case]
    if case in EXTRA_MB:
        assert extra <= EXTRA_MB[case]


if __name__ == "__main__":
    child(*sys.argv[1:])
