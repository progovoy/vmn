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

`fgm` / `fgm-small` / `fgm-tiny` (plan 28 B0) are static profiles shaped like
fgm's walk-forward store: app `fastglobalmacro`, per launch launch → date →
study → trial / refit / refit_single / refit_expansion / assembler → pod (5
levels; 60 dates × 4 studies × 40 children + a pod each, ~19.4k runs) plus a
`cost_report`. Every run carries `tags.kind` (and `trade_date` / `group` /
`target` from its date or study down), trials and refit_single runs a
`health` tag (BCA's unstable share grows with the trade date), a few a
`state` tag; the launch and the studies declare `progress` /
`progress_total`; `value` / `best_value` are declared `goal: max`. The
newest launches are live (20 dates done, 20 in flight: running, waiting,
and a 70-min eviction wave of released runs); finished ones leave a few
released, never-started and orphaned (stuck) runs that settle.

| profile | launches (live) | runs | running |
|---|---|---|---|
| fgm | 32 (4) | ~594k | ~10.3k |
| fgm-small | 3 (1) | ~51.5k | ~2.6k |
| fgm-tiny | 2 (1) | ~280 | ~30 |

`fgm_tree` plans the specs (stdlib only), `fgm_records` turns them into the
SDK's records or an in-memory index snapshot, `seed_fgm` writes a layout-2
store (a slice of a launch per worker) with fgm-like store settings
(`ui.attention` queries, `ui.split_by: tags.kind`), `probe_fgm` serves it
in-process and times `experiments-status` (with those attention counts), the
live launch's summary with and without `?split=tags.kind`, three grouped boards
and P1's waiting count (`ago()`, a fresh minute per request so each rebuilds,
plus one cold count first) against `slo.FGM_BUDGETS`. Seeded live runs declare a heartbeat interval of
months, so they read `running` long after seeding while the orphans read
`stuck`:

```sh
python packages/vmn-exp/tests/uiload/seed_fgm.py /tmp/fgm --profile fgm   # ~594k records, ~1 h
python packages/vmn-exp/tests/uiload/probe_fgm.py /tmp/fgm                # waits for the index
vmn-exp ui --repo /tmp/fgm                                                # or look at it
# in-memory baselines (serial; fgm-small by default, the full shape needs ~10 GB):
VMN_UILOAD_FGM_PROFILE=fgm python -m pytest -s -n0 -p no:cacheprovider \
    packages/vmn-exp/tests/test_uiload_fgm_bench.py
```

`test_uiload_fgm_shape.py` checks the plan's shape, `test_uiload_fgm_records.py`
its fold, `test_uiload_fgm_store.py` seeds and probes the tiny profile.

The UI server runs with `VMN_EXP_MIN_STALE_SEC` lowered so hung jobs turn
`stuck` within seconds. Everything lands in `--run-dir` (default a new temp
dir): `uiload/` (the data root, re-servable with `vmn-exp ui --repo`),
`events/` (the manifest the oracle reads), `ui.log`, `workers.log`,
`report.json`.

`s3bench` times a real `vmn-exp ui --store s3://...` (run from `--src`'s
package sources, so a baseline and a fix checkout compare) over a
production-shaped store: app `fastglobalmacro`, three outer runs (15, ~half,
the rest) plus single runs, and `--stuck` runs left `running` with stale
heartbeats and `--segments` uncompacted `.vms` + log segments each. The S3 is
a moto server (`moto[server]`) adding `--latency-ms` to every request
(`s3bench_moto`); the store is seeded once into `--data` (`s3bench_seed`:
pickled shards loaded straight into moto's backend) and reused while the
sizes match. It reports the cold index load, the Compare / outer-run Curves
`POST .../series` (cold, warm), the Single runs board's filtered rows under
`--clients` SSE tabs with hover prefetches (`s3bench_load`), SSE change
events, the 304 rate and the S3 requests of each phase.

```sh
python packages/vmn-exp/tests/uiload/s3bench.py --src . --runs 2000 --stuck 50 --segments 50 \
    --duration 20 --data /tmp/s3bench-smoke --out report.json
```

Modules: `scenario` (profiles, job planning) · `oracle` (events → expected
status) · `seeder`/`seed_records` (bulk history) · `seed_series`/`probe_series` (bigseries) · `fgm_tree`/`fgm_leaf`/`fgm_records`/`seed_fgm`/`probe_fgm` (fgm) · `s3bench*` (S3 store bench) · `worker`/`child` (live
jobs) · `spawner` (population, signals) · `ui_server` · `probe*`/`slo` (API
load + budgets) · `browser*` (Playwright) · `live_view` · `driver` · `run`.
