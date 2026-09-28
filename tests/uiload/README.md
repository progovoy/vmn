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
python tests/uiload/run.py live --profile smoke --port 8300 --duration 0

# assert it: runs the profile, prints report.json, exits 1 on any failure
python tests/uiload/run.py check --profile load
VMN_UILOAD_PROFILE=smoke python -m pytest -s tests/test_uiload_profile.py
```

| profile | seeded runs | live jobs | duration | stale floor |
|---|---|---|---|---|
| smoke | 500 | 30 (+2 sweeps × 5) | 45s | 5s |
| load | 100k (200 sweeps × 50) | 500 (+20 sweeps × 20) | 5 min | 8s |
| soak | 250k | 2000 | until Ctrl-C | 10s |

The UI server runs with `VMN_EXP_MIN_STALE_SEC` lowered so hung jobs turn
`stuck` within seconds. Everything lands in `--run-dir` (default a new temp
dir): `uiload/` (the data root, re-servable with `vmn-exp ui --repo`),
`events/` (the manifest the oracle reads), `ui.log`, `workers.log`,
`report.json`.

Modules: `scenario` (profiles, job planning) · `oracle` (events → expected
status) · `seeder`/`seed_records` (bulk history) · `worker`/`child` (live
jobs) · `spawner` (population, signals) · `ui_server` · `probe*`/`slo` (API
load + budgets) · `browser*` (Playwright) · `live_view` · `driver` · `run`.
