# Plan 28: handover (2026-10-28)

State of implementing docs/plans/28-training-health-at-a-glance.md. Delete
this file once the work below is done.

## On master (not pushed; 66 commits ahead of origin/master)

These items are merged:
- A0, P1, P2, P3, P4, T2a, T2b, N1, N2, N3, N4, N6, FS, API2, API3 and B0.
- The S3 SlowDown fixes.
- The appendix A ops fixes, rows 1–5.

Fixes from the end of this session:
- `4ca9a8b0`: a Jobs row's attention summaries are keyed by `ui.progress`,
  in `ui/attention.py`.
- `ccae65a1`: `experiments-status` takes its snapshot once (`routes_shell.py`
  `summary` gets the schema via `schema_of(ws, app, snapshot)`; `server.py`
  `_status_schema`). Before this, a cold index waited 0.5 s twice.
- `c57a1647`: two tests were edited with the user's approval to match A0:
  - the fakes in the diag board-warm test gain `conf_of` and `summarized`;
  - the S3 warm-restart test ignores GETs under `settings/`.

## Stopped unfinished

The GC-pauses investigation (appendix A row 6, GC pauses on 3.15.2t) was
stopped before it reported. Its heap-size bench, a script and not a pytest
test, is committed as `packages/vmn-exp/tests/gc_pause_bench.py`, with no
results. Next steps: run it on 3.15.2t, then mark row 6 Fixed or Explained
in appendix A.

## Not done

**Remaining plan items:**
- Live/Review `view=` presets. They need N3 and N6, which are both in now.
- N5, the run-page overlay.
- N7, notes as data. It was re-scoped after API2.
- N8, a per-metric display hint.
- Heartbeat env vars and a conditional beat.
- T2c, cost. It is deferred.

**N6 follow-ups:**
- Make the tree the Runs tab's default: set `DEFAULT_LAYOUT = "tree"` in
  `webui/src/pages/Job/JobRunsTab.tsx`. This needs user approval, because it
  breaks seven tests that pin the flat board:
  - `JobPage.test.tsx`;
  - `JobPageAttention.test.tsx`;
  - `JobPageFirstPaint.test.tsx`, 3 tests;
  - `JobRunsBack.test.tsx`, 2 tests;
  - N6's own `JobRunsLayout` "flat until chosen" test.
- The tree ignores the Runs tab's filters. The server already supports
  `q`/`status`/`sort` on `children_of`.
- Add the tree expander to the phone cards.

**B0 follow-ups:**
- Use the real `ago("1h")` attention query in the probe.
- Seed store settings (`ui.attention` and `split_by: tags.kind`).
- Measure 588k runs over HTTP on free-threaded Python.
- B0's skipped /simplify items are listed in its plan-28 §7 entry.

**Other:**
- Appendix A row 2: no per-prefix S3 request cap.
- In inline-refresh mode, an app's settings file is read 4 times per request
  (recheck 0). A per-request memo would make that once.
- The UI's index IO subprocess imports `vmn_exp` from the main checkout, not
  from a worktree. Keep that in mind when benchmarking in worktrees.

## Before calling it done

Run the full Python and web suites once (`./packages/vmn-exp/tests/run_pytest.sh`,
`./tests/run_pytest.sh`, web vitest + `tsc --noEmit`). Per-merge runs were
targeted only, as the user asked.

Timing benches flake under load: `test_ui_attention_bench` hit 1.08 s against
a 1.0 s cap at load average 50. Rerun them alone before treating one as a
regression.

## Open question for the user

Two uiload `worker.py` processes, 16 days old, are still running (PIDs 81662
and 81663, under /tmp/vmnux). They come from an earlier session. Kill them?
