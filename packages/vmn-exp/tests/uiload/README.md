# uiload — live load harness for `vmn-exp ui`

Seeds historical runs, keeps a population of **real** SDK / `vmn-exp run` jobs
reporting in parallel (succeed, crash, oom, stuck, recovers, killed, chatty,
wide, endless; outer sweeps with inner runs), serves them with a real
`vmn-exp ui` process and measures it: API latency per route, 304 rate,
freshness (writer → dashboard lag), oracle-vs-API status agreement, and
browser responsiveness (Playwright).

```sh
source ./venv/bin/activate
python -m playwright install chromium          # once

# watch it: prints the URL, redraws expected-vs-API counts + latency until Ctrl-C
python packages/vmn-exp/tests/uiload/run.py live --profile smoke --port 8300 --duration 0

# assert it: runs the profile, prints report.json, exits 1 on any failure
python packages/vmn-exp/tests/uiload/run.py check --profile load
VMN_UILOAD_PROFILE=smoke python -m pytest -s packages/vmn-exp/tests/test_uiload_profile.py
```

| profile | seeded runs | live jobs | duration | stale floor |
|---|---|---|---|---|
| smoke | 500 | 30 (+2 sweeps × 5) | 45s | 5s |
| load | 100k (200 sweeps × 50) | 500 (+20 sweeps × 20) | 5 min | 8s |
| soak | 250k | 2000 | until Ctrl-C | 10s |

`bigseries` / `bigseries-tiny` (plan 12 §10 4b) are static metric-volume
profiles, no live jobs: 50 runs × 1M steps × 50 keys, 1 run × 10k steps ×
5000 keys and 1000 overlay runs (one `loss` key). `seed_series.py` writes the
runs' `metrics/<writer>.vmx` with the real codec instead of logging the points
(the full profile takes tens of GB of disk and a while to build);
`probe_series.py` serves the root in-process and checks `slo.SERIES_BUDGETS`:
series p95 ≤ 150 ms at 2000 points, zoom p95 ≤ 150 ms, run-page detail ≤ 1 MB,
a 1000-run overlay ≤ 2 s. `test_uiload_bigseries.py` runs the tiny variant.

```sh
python packages/vmn-exp/tests/uiload/seed_series.py /tmp/big --profile bigseries
python packages/vmn-exp/tests/uiload/probe_series.py /tmp/big --profile bigseries
```

The UI server runs with `VMN_EXP_MIN_STALE_SEC` lowered so hung jobs turn
`stuck` within seconds. Everything lands in `--run-dir` (default a new temp
dir): `uiload/` (the data root, re-servable with `vmn-exp ui --repo`),
`events/` (the manifest the oracle reads), `ui.log`, `workers.log`,
`report.json`.

Modules: `scenario` (profiles, job planning) · `oracle` (events → expected
status) · `seeder`/`seed_records` (bulk history) · `seed_series`/`probe_series` (bigseries) · `worker`/`child` (live
jobs) · `spawner` (population, signals) · `ui_server` · `probe*`/`slo` (API
load + budgets) · `browser*` (Playwright) · `live_view` · `driver` · `run`.
