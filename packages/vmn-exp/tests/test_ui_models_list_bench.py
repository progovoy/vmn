"""Benchmark: the Models page on a registry the size of fgm's (241 models,
7.7k versions took ~45 s on S3) with every registry read a 30 ms round
trip. The cold server's first answer comes within seconds; a warm one is
instant and reads no store."""
import itertools
import time

import pytest
from bench_timing import fastest_each

pytest.importorskip("fastapi")

from models_registry_fixture import (  # noqa: E402
    MODELS, build_registry, registry_reads, store_client, store_storage,
)

N_MODELS, N_VERSIONS = 250, 32
LATENCY = 0.03
COLD_SEC, WARM_SEC = 4.0, 0.5


@pytest.mark.serial
def test_the_models_page_answers_a_big_registry_within_seconds(tmp_path):
    attempts = itertools.count()
    passes = []
    took = fastest_each(lambda: _cold_then_warm(tmp_path / f"a{next(attempts)}", passes),
                        {"cold": COLD_SEC, "warm": WARM_SEC})
    rows, warm_rows, warm_reads = passes[-1]

    print(f"\nmodels list: cold {took['cold']:.2f}s, warm {took['warm']:.3f}s (uncontended)")
    assert warm_rows == rows
    assert len(rows) == N_MODELS
    assert sum(r["versions_count"] for r in rows) == N_MODELS * N_VERSIONS
    assert sum(1 for r in rows if r["aliases"]) == 50
    assert took["cold"] < COLD_SEC
    assert took["warm"] < WARM_SEC
    assert warm_reads == []


def _cold_then_warm(root, passes):
    """A cold server on a fresh registry under *root*, asked twice:
    ``{cold, warm}`` seconds; the answers and warm reads appended to *passes*."""
    build_registry(store_storage(root), N_MODELS, N_VERSIONS, aliased=50)
    app, client = store_client(root, background=True)
    with pytest.MonkeyPatch.context() as monkeypatch:
        reads = registry_reads(monkeypatch, LATENCY)
        try:
            started = time.monotonic()
            rows = client.get(MODELS).json()["models"]
            cold = time.monotonic() - started
            reads.calls.clear()
            started = time.monotonic()
            warm_rows = client.get(MODELS).json()["models"]
            warm = time.monotonic() - started
        finally:
            app.state.refresher.stop()
    passes.append((rows, warm_rows, list(reads.calls)))
    return {"cold": cold, "warm": warm}
