"""Similar runs at scale (plan 24 F1): the synthetic store of
:mod:`scale_store` (a 20k-word vocabulary, 150-word intents, changed files
and symbols, a third of the runs inner runs), its experiment index built
once and cached (:mod:`similar_bench`).

Budgets at 100k runs (``VMN_SCALE_BENCH=1``): a fresh process answers a full
query (a run's code, params, intent) within 1 s and a text-only one within
0.3 s, a warm process within 0.1 s, a save refiles 100 changed runs within
0.2 s, and a query adds at most 150 MB of resident memory. The 20k-run
variant runs always, under budgets scaled by 0.3. A fresh process's time is
its wall time to the first answer minus the wall time of a process that only
imports (Python start and the CLI's imports, measured in the same run; both
printed). What is timed is the search over the persisted index file;
bringing the index up to date with the store is the index's own cost
(plan 25).
"""
import os

import pytest
from similar_bench import indexed_store, measure, refile_seconds, target_verstr

SCALE = {20_000: 0.3, 100_000: 1.0}
FULL_SEC, TEXT_SEC, WARM_SEC, REFILE_SEC, RSS_MB = 1.0, 0.3, 0.1, 0.2, 150


def _runs(n):
    if n > 20_000 and os.environ.get("VMN_SCALE_BENCH") != "1":
        pytest.skip("set VMN_SCALE_BENCH=1 for the 100k-run benchmarks")
    return n


@pytest.fixture(scope="module", params=sorted(SCALE), ids=lambda n: f"{n // 1000}k")
def store(request):
    n = _runs(request.param)
    return n, indexed_store(n)


def _measured(n, built, kind, verstr=None):
    got = measure(*built, kind, verstr)
    print(f"\n{n} runs, {kind} query: wall {got['wall']:.3f}s - import baseline "
          f"{got['baseline']:.3f}s = {got['cold']:.3f}s cold, {got['warm']:.3f}s warm, "
          f"+{got['rss_mb']:.0f} MB")
    return got


@pytest.mark.serial
def test_a_full_query_answers_within_budget_cold_and_warm(store):
    n, built = store
    got = _measured(n, built, "run", target_verstr(built))
    assert got["items"] == 10
    assert got["cold"] <= FULL_SEC * SCALE[n], got
    assert got["warm"] <= WARM_SEC * SCALE[n], got
    assert got["rss_mb"] <= RSS_MB * SCALE[n], got


@pytest.mark.serial
def test_a_text_only_query_answers_within_budget_cold_and_warm(store):
    n, built = store
    got = _measured(n, built, "text")
    assert got["items"] == 10
    assert got["cold"] <= TEXT_SEC * SCALE[n], got
    assert got["warm"] <= WARM_SEC * SCALE[n], got
    assert got["rss_mb"] <= RSS_MB * SCALE[n], got


@pytest.mark.serial
def test_a_save_refiles_a_hundred_changed_runs_within_budget(store):
    n, built = store
    assert refile_seconds(*built) <= REFILE_SEC * SCALE[n]
