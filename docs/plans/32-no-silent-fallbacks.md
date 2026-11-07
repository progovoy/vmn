# Plan 32: no silent fallbacks

> Plan 31 found that baselines pair a child's own metric with another child's
> subtree best without saying so (`ui/baseline_views.py:201`). The owner's
> rule (2026-11-07): **a number may not silently switch its source or
> meaning.** An audit of `core/`, `ui/`, `cli/` and the web client found more
> places that break it. This plan lists them and fixes them under one rule.
>
> Paths: `core/` = `packages/vmn-exp-sdk/src/vmn_exp/…`; `ui/`, `cli/` =
> `packages/vmn-exp/src/vmn_exp/…`; web = `packages/vmn-exp/webui/src`; tests
> in `packages/vmn-exp/tests/`.

Status: **done** (2026-11-07). Code read at `1ce18300` (vmn_exp 0.1.34).
Progress: **all items done** (F1-F16 and the reports/export audit), on
master `1f6133c7..b53ad3bc`.
- Goals (F4-F7, F12): beyond the plan, the web no longer guesses a goal from a
  metric's name (`loss` → min, `acc` → max). It reads goals from the server,
  which resolves glob goals per name (`metrics-schema`) and puts a `goal` on
  each baseline metric and group aggregate. A board hint asks users to declare
  missing goals.
- F1: `metric_policy` lists only a run's overrides of the schema (an explicit
  `last` included), not every non-`last` value. Listing every value gave false
  tags for metrics logged once and cost about 1 KB per row per schema view.
  `DERIVED_VERSION` 21: a local re-derive, no storage reads.
- F8: `RECORDS_VERSION` 19. Version-18 records are copied; only runs with a
  param also logged as a metric are re-read from storage (`COPYABLE_RECORDS`
  predicates, `core/index_reread.py`).

Follow-ups (not in this plan):
- ✓ The board's shared `declared_schema` merged run-declared goals with the
  latest run winning. Now the conf goal wins, else the runs' one goal; runs
  declaring different goals give none (`goal_conflict`, `goals` counts, web
  `(goals differ)`), counts kept per generation (`core/goal_counts.py`).
- ✓ F1's `mixed` flag on pivot cells, Jobs rollup metrics and the baseline
  card is shown by the web (a `*` titled `2 runs use min`); CLI
  `compare`/`diff` name policies and say `summaries differ: min vs last`.
- The single runs' own-value column on the Jobs view is plan 31 §2's.
Items marked ✓ were checked against the code by hand. The rest come from the
audit and are re-checked when their test is written.

## 0. The rule

1. **A value names its source.** When a value can come from more than one
   source (summary type, progress kind, goal), the payload carries which one
   it came from, and the web shows it when a column, chart or sort mixes
   sources.
2. **No guessed meaning.** A metric without a declared goal has no "best", no
   better/worse verdict and no ranking. It shows `(no goal)`. Its sort
   defaults to ascending, the same everywhere.
3. **Missing is missing.** An absent value is `—` or not drawn, never 0 and
   never a value from another source.
4. **What is shown is what sorts.** A column sorts by the field its cell
   displays.

No compatibility: results change where they were wrong.

## 1. High: different measures shown, compared or sorted together with no marker

### F1 ✓ A metric column mixes summary types between runs

`core/metric_summary.py:219-247` (`SchemaPolicies.of`, `with_schema_policies`):
a run's value follows its own `define_metric` summary first, then the conf
schema, then `last`. A min/max/mean summary with no finite value becomes
`last`. In one `metrics.loss` column, run A can show its min while run B shows
its last value. The board, sorting, `q=`, CLI `list`, group/pivot aggregates,
the Jobs best and compare all read it.

Fix:
- `with_schema_policies` also returns `{metric: policy}` for every value it
  set, kept on the row as `metric_policy`. Values left at their last value
  aren't listed.
- A summary with no finite value leaves the metric missing (rule 3). It
  doesn't become `last`.
- Web: a cell whose run's summary differs from the column's (the schema's)
  shows a small tag (`min`). The header reads `loss · mixed` when the loaded
  rows differ.
- CLI `list`/`show` print `loss=0.12 (min)` when the summary isn't `last`.
- Group/pivot/rollup aggregates over a column with mixed summaries carry
  `mixed: true`. The cell title then says "3 runs use min".

Tests first: two runs with different `define_metric` summaries show their
`metric_policy`; an empty min summary is missing, not last; the CLI output;
the `mixed` flag on a group.

### F2 ✓ Throughput shows one number and sorts by another

When a training declares progress, the cell shows declared units per minute
since start (`webui/src/util/jobProgress.ts:41-46`). `job:throughput` sorts
on `throughput_per_min`, runs per minute over the last 10 minutes
(`ui/leaderboard_jobs.py:28`).

Fix: split it into two fields and two columns, `job:rate` (declared progress
per minute, `—` without one) and `job:throughput` (runs per minute, always).
Each sorts by what it shows. The cell never switches.

### F3 Progress and ETA switch source per training

`ui/job_rollup_payload.py:117-120`: with declared progress, `progress` and
`eta_sec` come from the declared done/total and its rate; otherwise from runs
done/expected and the 10-minute throughput. `job:progress` sorts both kinds
together, and the gauges `vmn_job_progress`/`vmn_job_eta_seconds`
(`ui/rollup_gauges.py:76-77`) have no label saying which kind they are.

Fix:
- The payload carries `progress_source: declared|runs`.
- The gauges get a `source` label.
- `job:progress` keeps sorting by the fraction. Both kinds are fractions of
  their total, so sorting them together is fine, but the cell names its unit
  (it already does in the web, `declared_progress`).
- `jobTimeState` (`jobProgress.ts:79-84`) reads ended/never-started from the
  same source as the shown progress.

### F4 ✓ The goal is guessed from whether a name is in the schema

`core/log.py:117-123` `sort_descending`: no goal and not in the schema means
ascending; no goal but in the schema means descending. The effective schema
includes the latest run's declarations, so one run declaring only `hidden`
or `chart` flips a metric's default sort app-wide. The web defaults to `desc`
for any column without a min goal (`webui/src/pages/boardSortState.ts:14`);
the CLI sorts ascending.

Fix (rule 2):
- `sort_descending` uses the goal only. No goal means ascending, in core, the
  web and the CLI.
- `RollupSpec.descending` (`ui/job_tally.py:71`) and the group sort
  (`ui/leaderboard_group_spec.py:45`) take the goal from the same function
  and rank nothing without one (F5).

### F5 ✓ Verdicts assume a goal the payload says doesn't exist

`ui/job_tally.py:66-72`: the primary metric is ranked even without a goal,
with `descending` from F4's guess, so the Jobs "best" is the max.
`ui/baseline_views.py:166-170,196`: the payload says `goal: null` while the
chip computes worse/better as higher-is-better, and the web shows no arrow.

Fix: a primary metric without a goal is shown but not ranked. It gets no
"best", no chip verdict and no worse/better marks; spread and deltas are
shown without a direction. The payload's `ranked` is per metric.

## 2. Medium: a number under a misleading label

| | Where | Fix |
|---|---|---|
| F6 ✓ | `ui/leaderboard_group_summary.py:30-31`: `best` without a goal becomes the mean. Group headers mark it; pivot cells (`ui/pivot.py:85-92`, web `JobPivot.tsx`) and the group sort (`leaderboard_group_spec.py:71`) still say `best` | `best` without a goal is `—`/`(no goal)` everywhere, and the payload's `agg` is what was applied |
| F7 | `ui/readers/baselines.py:65-98`: the "best" baseline uses the primary metric if it has a goal, else the first metric with one; the response names no metric | The response carries `metric`; no metric with a goal means no "best" baseline |
| F8 | `core/fold.py:237-242`: numeric params fold into `metrics`, the last write wins; `ui/readers/diffs.py:107-109` and `webui/src/pages/leaderboardColumns.ts:224-240` then misclassify the name | A param never overwrites a logged metric of the same name; `diffs` and the column picker key on the logged metric |
| F9 | `ui/readers/diffs.py:124-130`: compare takes the goal from run 1, else run 2, else the schema; the snapshot path takes the latest run's | One goal from the app's effective schema for both runs; when the two runs declare different goals, the delta has no direction and says `goals differ` |
| F10 | `webui/src/pages/Experiments/jobColumns.ts:56-61` picks the main metric differently from the server (`job_tally.py:70-72`); the same column mixes a training's subtree best with a single run's own value | The web uses the server's `main` from the page payload. The single runs' own values get their own column (plan 31 §2 already separates the sources) |
| F11 | `core/alerts/transitions.py:49-58,136-147`: the stuck alert uses `heartbeat or started_at`, while the stuck status uses the fresher of the heartbeat and the store write time (`core/status.py:187-200`) | The alert takes its time from the same function as the status; the message says "no heartbeat since start" when there never was one |
| F12 | `webui/src/components/GroupedMetrics.tsx:90-91`: a missing group mean is drawn as 0 | No bar, labelled `—` |

## 3. Low

| | Where | Fix |
|---|---|---|
| F13 | `core/status.py:241-246`: `duration_sec` is now minus start for a run that never finished, so a stuck run's duration keeps growing and sorts with final durations | A run that is not running carries `duration_sec: null` plus `duration_at_least_sec` (its last heartbeat minus start); the web and CLI show `≥ 3h (stuck)`, and it sorts after the known durations |
| F14 | `webui/src/pages/Experiments/JobRow.tsx:20`, `JobCards.tsx:47`: "when" shows `job.started_at ?? started_at ?? timestamp`; `job:started` sorts on `job.started_at` only | Show and sort the same field; the creation time is labelled `created` when the run never started |
| F15 | `ui/rollup_gauges.py:100-103`: the end used to include a run in the gauge window falls back to the creation time | Leave as is (it only decides inclusion), but document it |
| F16 | `core/sweep/summary.py:73-78,141-148`, `cli/sweep/handler.py:99-103`: a trial's own metric, else its best descendant's. Marked per trial (`metric_source`), but not in `summary.best` or `sweep status` | Carry `metric_source` on `summary.best` and print it |

Checked and clean: status rollups (`core/tree.py`, `ui/status_summary.py`),
baseline deltas (`ui/baseline_views.py:51-60`), group-of-jobs aggregates,
step-metric joins, cursor projections, config precedence (the applied value is
reported). Reports and export, audited 2026-11-07: pinned-run panels
labelled runs by their position (`@1`, `@2`; `reports/panelData.ts`), and
the bar chart ranked a goal-less metric descending as "the top 50"; both
fixed. Also fixed: "Add to report" saved the chart's first metric and
default axes (`reports/viewSpecs.ts`, `grouped` always by `branch`); it now
saves the metric, axes and group the reader picked (the charts report them
through `onChoice`). An exported image left out was a blank `src`
(`reports/export.tsx`); the export now records each skipped URI with why,
and the page shows "not included in export (over N MB)" or "(file
missing)". A published panel asking for a query it did not capture showed
"Loading…" forever (`reports/publishedData.tsx`); the frozen cache now fails
it and the panel says "not published with this report". The job page's
main metric fell back to the first tracked metric with values
(`pages/Job/jobData.ts`); it now reads only the server's, and the best tile
reads `—` with "(no main metric)" or "(no values yet)". Server side
(`ui/reports_publish.py`, `cli/report_export.py`, `core/panel_spec.py`)
computes no values: clean.

## 4. Order

Each worktree runs TDD; `/simplify` at the end.

1. **F4 + F5 + F6 + F7 (goals).** One worktree: a single `goal_of`/`ranked`
   path, then each consumer. Lands before plan 31 §2, which ranks on the same
   goal.
2. **F1 (summary type).** Core `metric_policy` and missing-not-last, then the
   web/CLI tags. Two worktrees (core, web).
3. **F2 + F3 + F14 (Jobs columns).** One worktree each for server and web.
4. **F8, F9, F11, F12, F13, F16.** Small; parallel.
5. The reports/export audit.

Plan 31 §2's no-fallback baseline change is done there (it is the same code).
F10's column split is also done there.

## 5. Decisions (2026-11-07)

1. F1: a run's own `define_metric` summary overrides the conf schema, and the
   override is shown (the F1 fix).
2. F4: a metric without a goal sorts ascending, with `(no goal)` in the
   header.
3. F13: a stuck run's duration reads `≥ 3h (stuck)`, marked, and sorts as
   unknown (after the known durations).
