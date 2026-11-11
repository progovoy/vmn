"""Benchmark: the Models page on a registry the size of fgm's (241 models,
7.7k versions took ~45 s on S3) with every registry read a 30 ms round
trip. The cold server's first answer comes within seconds; a warm one is
instant and reads no store."""
import time

import pytest

pytest.importorskip("fastapi")

from models_registry_fixture import (  # noqa: E402
    MODELS, build_registry, registry_reads, store_client, store_storage,
)

N_MODELS, N_VERSIONS = 250, 32
LATENCY = 0.03
COLD_SEC, WARM_SEC = 4.0, 0.5


@pytest.mark.serial
def test_the_models_page_answers_a_big_registry_within_seconds(tmp_path, monkeypatch):
    build_registry(store_storage(tmp_path), N_MODELS, N_VERSIONS, aliased=50)
    app, client = store_client(tmp_path, background=True)
    reads = registry_reads(monkeypatch, LATENCY)
    try:
        started = time.monotonic()
        rows = client.get(MODELS).json()["models"]
        cold = time.monotonic() - started
        reads.calls.clear()
        started = time.monotonic()
        assert client.get(MODELS).json()["models"] == rows
        warm = time.monotonic() - started
    finally:
        app.state.refresher.stop()

    print(f"\nmodels list: cold {cold:.2f}s, warm {warm:.3f}s")
    assert len(rows) == N_MODELS
    assert sum(r["versions_count"] for r in rows) == N_MODELS * N_VERSIONS
    assert sum(1 for r in rows if r["aliases"]) == 50
    assert cold < COLD_SEC
    assert warm < WARM_SEC
    assert reads.calls == []
