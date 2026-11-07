# Plan 31: fgm feedback, November round (triaged)

> fgm (app `fastglobalmacro`, plans 28-30) sent seven "can't fix on our side"
> items, two doc errors and measurements from a 737k-run S3 store (3.15.2t:
> 18 GB RSS after 40 min loading from the built index; warm board pages in
> ~10 ms, an outer run's summary in 0.1-0.2 s). This plan triages them, designs
> the ones we take and drafts the reply.
>
> Paths: `core/`, `storage/` = `packages/vmn-exp-sdk/src/vmn_exp/…`; `ui/`,
> `cli/` = `packages/vmn-exp/src/vmn_exp/…`; web = `packages/vmn-exp/webui/src`;
> tests in `packages/vmn-exp/tests/`.

Status: **proposal** (2026-11-07). Code read at `1ce18300` (vmn_exp 0.1.34).

## 0. Triage

| # | Ask | Decision | Section |
|---|---|---|---|
| 1 | A tree reads `failed` if any run in it failed | Keep the rollup. Make the failure share queryable (`top_q=failed_pct > 5`) | §1 |
| 2 | Choose the rollup on the Outer runs row (median of date bests, p90) | Build it: `job_agg` + `job_agg_by` | §2 |
| 3 | Cold group-by (19 s first, then 0.02 s) | Warm grouped **team** views. **On hold** | §3 |
| 4 | `experiments-status` stuck 902 + lost 7774 vs `q=status = "stuck"` 8,676 | Docs + test: `settled` already separates them | §4.1 |
| 5 | `q=kind = "launch"` silently empty; `view=` ignored on the API | Hint on a never-matching field; 400 on web-only params | §4.2 |
| 6 | `prune -v` reads the registry one object at a time (~16k, ~15 min/call) | Parallel read | §4.3 |
| 7 | `vmn-exp[ui]` without `s3` serves `--store s3://`, then 500s | Fail at startup | §4.4 |
| D1 | API table lists `ws/{ws}/apps/…` | Write full paths | §5 |
| D2 | ui.md says use a GIL build past 200k runs | Reverse it: their data and ours favour 3.15t | §5 |

## 1. The failure share in a query (#1)

**Why not a new tree status.** A "succeeded with failures" status would only
relabel the 29 of 45 trees. Every status consumer would need to know it
(alerts, `experiments-status`, query values, web colours). It also hides a 40%
failure share just as `failed` hides a 0.03% one, unless we add a threshold.
`failed_pct` already exists on each outer run's rollup
(`ui/job_rollup_payload.py:84`, `(failed + lost) / total`) and sorts
(`job:failed_pct`). It just can't be filtered on.

**Today.** `top_q` reads the row's own fields plus `core/query.py`'s
`BELOW_FIELDS` (`live_below`, `running_below`, `stuck_below`, computed lazily by
`core/query_below.py`, so a query that doesn't read them costs nothing).
`failed_pct` isn't a field, so `top_q=failed_pct > 5` is a query error.

**Change.**
- Add `failed_below` (failed + lost runs below the row) and `failed_pct`
  (`100 * failed_below / runs below`, 0 without children) to `BELOW_FIELDS`.
  They follow the existing membership rule (counted status, stop at the nearest
  archived run). A lost run counts as failed, matching the rollup's
  `failed_pct`.
- Unlike the live counts, these need a pass over every run, not just the live
  ones. Compute them in the same lazy first read and memoize them per snapshot
  extra (`core/query_extra.py`), so the cost is paid only by queries that read
  them.
- Web: the Outer runs status chip **failed** gains a "≥ N% failed" option that
  sends `top_q=failed_pct >= N`. The default N comes from
  `experiment.ui.failed_pct_threshold` (default 5). It's a filter, not a status.
- Docs: ui.md Outer runs (the chips) and the row-fields table.

**Tests first.**
- `core`: `failed_below`/`failed_pct` on a three-level tree with failed, lost,
  archived and never-started runs. Check them against `job_rollup_payload`'s
  `failed_pct` for the same tree.
- Route: `top=jobs&top_q=failed_pct > 5` keeps only the high-failure trees.
- A query not reading the fields doesn't compute them.

Size: ~80 lines plus tests, plus ~40 lines of TS.

## 2. A chosen aggregate on the Outer runs row (#2)

**Today.** The row's metric value is the subtree's best: `job_summary`'s
`best`/`best_verstr` (`ui/job_rollup_payload.py`). It is built from
`StaticRollups` (`ui/job_rollup.py`), one `Tally` per direct parent, carried
across generations by the cache deltas, with a live overlay per bucket. A job
reads the tallies of `JobTree.subtree_jobs(job)`. `MetricTally`
(`ui/job_tally.py`) already holds n, sum, extremes and a removable
`QuantileSketch` (~1%). Baselines (`ui/baseline_views.py` `_child_value`)
already compute "the child's own metric, else its subtree best".

**Why the median over the whole subtree is the wrong default.** A median over
every trial measures the search space, not the model. Walk-forward needs the
nested number: the best trial within each date, then the median across dates.

**Design.**
- `job_agg` ∈ `mean|best|median|min|max|best10|worst10`. This is the
  group-by vocabulary plus two tails that follow the metric's goal. The label
  names the percentile: higher-is-better reads `best10 (p90)` /
  `worst10 (p10)`, lower-is-better flips them. There is no raw p10/p90. A
  metric without a goal shows `— (no goal)`, as `best` does. Both tails are
  added to `GROUP_AGGREGATES`, so group headers get them too.
- `job_agg_by`:
  - `children` (default): one value per direct child, aggregated across
    children. Shown as "median of 16 date bests".
  - `kind:<tags.kind>`: the same per descendant whose `tags.kind` matches, for
    trees where the date level sits deeper.
  - `runs`: flat over all subtree runs, from the merged sketch. Opt-in, and
    labelled "≈ median of 16,384 runs".
- `job_agg_value` picks where each child's value comes from. There is
  **no fallback**:
  - `best` (default): its subtree's best run. Every child with a scored run
    has one.
  - `own`: the child's own logged metric, e.g. the out-of-sample score of the
    trial it selected. A child without it counts as missing and shows in the
    coverage ("median of 12/16 dates"), never as its best trial in disguise.
- `best` gives the same number for every `by`, so today's behaviour is
  `job_agg=best`.
- Every child with a value counts, finished or not; the coverage `n`/`of`
  says how many have one ("14/16").
- **Top-level rows only (pending the client, §7 Q3).** `children_of` tree
  rows keep their own values. At a
  date row, `by=children` would silently mean "median over trials", the number
  this feature exists to avoid. The compute is generic per job, so it would be
  cheap (~30 lines, ~765 tree rows); the meaning changing per level is the
  problem.
- **API:** `GET …/experiments?top=1&job_agg=median&job_agg_by=children&job_agg_value=best`.
  - A bad value, or `job_agg` without `top`, is a 400.
  - Both values go into the etag and into `Filters` (`ui/leaderboard_scope.py`).
  - Each row's `job` gains
    `rolled: {agg, by, source, percentile, value, n, of, verstr, approx}`.
    `n` of `of` covers dates with no value yet ("14/16"). `verstr` is the child
    holding the value (the lower neighbour for a quantile).
- **Sort:** `job:best` is renamed `job:value` (no shim). It sorts by
  `rolled.value`, best-first by the metric's goal.
- **Settings:** one aggregate per board, never mixed across rows.
  `experiment.ui.job_aggregate: {agg, by, value}` is the app's default. It
  lives in conf.yml or the store settings, validated in `core/app_settings.py`
  and resolved like `aggregate_of` (`ui/experiment_source.py`).
  - The URL overrides it.
  - Different kinds of outer run get their own aggregate through team views
    (a `tags.kind = "training"` view carrying its `job_agg`).
  - A row it doesn't fit (no children, or no `kind:` match) shows `—`.
- **Web:**
  - the column menu gets an Aggregate/By picker (the group Aggregate pattern);
  - the URL holds `job_agg`/`job_agg_by`;
  - the header shows `median · dates`;
  - the cell title reads "median of 14/16 date bests", or "median of
    12/16 dates' own sharpe" for `own`.
  - Files: `pages/Experiments/jobColumns.ts`, `JobCells.tsx`, `types.ts`,
    `apiJob.ts`, `pages/boardSortState.ts`.
- **Elsewhere:**
  - Baselines lose their silent fallback too (the rule and the other cases:
    [plan 32](32-no-silent-fallbacks.md)). `ui/baseline_views.py`
    `_child_value` today takes a child's own metric, else its subtree best,
    so one side of a date pair can be an own score and the other a best trial.
    - It moves into the new module as the shared value function with the
      board's explicit `job_agg_value`.
    - A pair missing a value from that source is unpaired and counts in the
      chip's total ("5 of 39 paired").
    - `rollup_deltas` adds a `rolled` delta, and `best_chip` without pairs
      compares `rolled`.
  - Outer-run overview: a KPI tile beside "best".
  - Grouped Jobs view: `JobGroups._aggregates` (`ui/leaderboard_group_jobs.py`)
    aggregates `rolled.value`.
  - `experiments-status`: unaffected.

**Cost.** No new incremental state.
- `rolled` is derived from the existing static tallies plus the overlay: per
  child job, the extremes merged over its parts.
- A job with ≤ 256 direct leaf rows is read exactly; otherwise its direct
  tally's sketch is used (marked approx).
- Memo: `{job: rolled}` per (base token, bucket, schema key, agg, by) in a
  tracked LRU. There's no minute in the key, so it doesn't churn every minute
  the way `job_summary` does.
- 45 outer runs × 16 dates is ~720 lookups, well under 1 ms. Deltas reuse
  `StaticRollups.advanced`, including the rebuild when a date's best is removed.

**Rejected.**
- Flat only: misleading.
- Walking subtree rows per request: O(rows), and against the snapshot invariant.
- A new per-parent tally: the existing one suffices.
- `up.<field>`/`params.<k>` as `by` in v1: an ancestor's param change isn't a
  delta of the rows below it. This is phase 2, as a `BestBySpec` tally like
  `_SplitRollups`.
- Computing it in the browser: it needs every child, and the column can't sort.

**Modules.**
- New `ui/job_aggregate.py` (~180 lines): `JobAgg` parse/check, `child_value`,
  `subtree_best`, `rolled_of`, and the `JobAggregates` memo.
- Edits: `ui/leaderboard_jobs.py`, `leaderboard_scope.py`,
  `routes_leaderboard.py`, `experiment_source.py`,
  `leaderboard_group_summary.py` (p10/p90), `baseline_views.py`,
  `baseline_compare.py`, `leaderboard_group_jobs.py`, `core/app_settings.py`.

**Tests first.**
1. `test_ui_job_aggregate.py` against a brute-force reference (extend
   `tests/job_rollup_reference.py`). Cases:
   - a training → 16 dates → trials tree gives the exact median/p90/min of the
     date bests;
   - `value=own` never falls back (a child without its metric is missing);
   - `best10`/`worst10` flip with the goal, and the percentile label;
   - `n`/`of`, running children included;
   - `children_of` rows carry no `rolled`;
   - archived children excluded;
   - `kind:` at depth 2;
   - the sketch path within 1%;
   - `best` is the same for every `by`.
2. Generation property test: random deltas give the same `rolled` after
   `advanced` as a fresh build. The deltas include a trial improving a date's
   best, the holder of a best being removed, and a re-link.
3. Settings validation (`job_aggregate`); group summary `best10`/`worst10`.
4. Routes: `job.rolled`, `job:value` order, the 400s, the etag per `job_agg`,
   settings vs URL.
5. Baselines: no own/best mixing within a pair (a child lacking the source
   value is unpaired and counted), the `rolled` delta, `best_chip` without
   pairs.
6. Serial benchmark: 45 × 16 × 1000 trials, the answer after a delta in
   under ~20 ms.
7. Vitest: cell title, header, URL round-trip, picker.

**Size.** ~400 lines of Python, ~450 of tests, ~200 of TS. Three worktrees:
(a) core + settings, (b) route/sort/baseline, (c) web.

**Decided (2026-11-07).**
1. No fallback; the source is the explicit `job_agg_value`.
2. Running children count, with coverage shown.
3. Direction-aware `best10`/`worst10` with the percentile in the label.
4. Strict: one aggregate per board; per-kind through team views.
5. Baselines share the no-fallback value function.

**Open (client, §7).**
- Q1 layout: are dates child runs, or `params.trade_date` on flat trials? If
  the latter, the `params.<k>` `by` (phase 2) is needed first.
- Q2: do dates log their own metric, and under what name?
- Q3: the aggregate on expanded tree rows too? Proposed: no (it would mean
  "median over trials" there).

## 3. Warm grouped team views (#3), on hold

`BoardWarmer` (`ui/leaderboard_warm.py`) warms each top view's first page at
startup and on every refresh, but never a grouped one. `GroupCache`
(`ui/leaderboard_group_cache.py`) carries a built grouping across generations
via its deltas (`_latest`), so only the first build is cold. The server can see
only **team views** (`experiment.ui.views`, `core/app_settings.py`
`views_entries`); personal views live in localStorage.

When resumed:
- A new `ui/view_warm.py` maps a team view's `{page, search}` to the
  `cache.groups(...)` arguments the web client sends:
  - `group`, `agg` (else the app default), `sort`, `q`, `status`, `archived`;
  - `top` from the page;
  - the first-page sizes from `routes_leaderboard.grouped_page`.
  - Views that aren't grouped, `job`-page views and unparseable views are
    skipped.
- `BoardWarmer._steps` adds one step per grouped team view.
- Tests: the mapping, a memo hit after `warm()`, and the grouping carried
  across a refresh.
- ~150 lines.
- Profiling the cold 19 s build itself is separate.

## 4. Bugs

### 4.1 Stuck vs lost (#4)

`experiments-status` reports the settled split: `stuck` excludes runs under an
ended outer run, which are reported as `lost`. `status = "stuck"` matches the
run's own status, which stays `stuck`. Both are correct. The derived `settled`
row field (ui.md row-fields table) already separates them:
`q=status = "stuck" and settled != "lost"` should give the 902.

- Test first: a route test that this query's count equals
  `experiments-status`'s `stuck` on a tree with lost runs. If `!=` against
  `null` doesn't match, fix the query instead.
- Docs: one sentence each in experiments.md (status counts) and ui.md
  (queries).

### 4.2 Silent empty results (#5)

- `kind` is a built-in row field (`core/query.py` `ROW_FIELDS`), so
  `q=kind = "launch"` compares the row kind, never `tags.kind`.
- When an equality on a row field matches no row, but the same value exists
  under `tags.<field>` or `params.<field>` in the facets, the response carries
  `hints: ["kind = \"launch\" matches nothing; did you mean tags.kind?"]`. This
  is computed from the facets, not a row pass, and only when the result is
  empty. The web shows it under the query bar.
- `view=`, `kind=`, `tab=` and `sel=` (web-only URL params) on
  `…/experiments` answer 400 `"view is a web page parameter; use top=jobs or
  q=…"`.
- Tests first: the hint is present and absent in the right cases; the 400s.

### 4.3 `prune -v` registry reads (#6)

Trace the registry check in `cli/prune*.py` first (not yet located). Expected
fix: read the registry objects with the store's parallel reader (as
`storage/s3_listing.py` does), once per call, not per batch.
- Test: the registry is read once per call whatever the batch size, and in
  parallel (a fake store that records concurrency).
- Target: the 16k objects in well under a minute.

### 4.4 S3 store without boto3 (#7)

`storage/s3_base.py:136` imports boto3 on first use. `vmn-exp ui --store
s3://…` (and a workspace on S3 in `server.yml`) checks
`importlib.util.find_spec("boto3")` at startup and exits non-zero with
`pip install "vmn-exp[ui,s3]"`. Test first, through the CLI with boto3 hidden.

## 5. Docs

- **D1:** ui.md's API table writes the full
  `/api/v1/workspaces/{ws}/apps/{app}/…` paths. The shorthand note at
  ui.md:805 is dropped.
- **D2:** ui.md "Large stores" (~L241-290). Recommend free-threaded 3.15t at
  every size, using their numbers (GIL 3.14 at 112 GB RSS after a cold index vs
  74 GB on 3.14t; 3.15.2t at 18 GB on 737k runs) and the plan 26 harness's.
  - Drop "Past ~200k runs, use a GIL build".
  - Remove or reverse the `vmn-exp ui` warning on 3.14t past 200k runs and the
    GIL hint (`ui/cli.py`), and update their tests.
  - Plan 26's gate ("flips the GIL hint back") is then done; mark it.

## 6. Order

1. §4.4, §4.1, §5 (small; parallel worktrees).
2. §1 and §4.2 (parallel).
3. §4.3 after tracing.
4. §2 after the open questions are answered (three worktrees), after plan 32's
   goal fixes (F4-F7), since §2 ranks on the same goal.
5. §3 when resumed.

Each worktree runs TDD; `/simplify` at the end.

## 7. Draft reply

1. **Tree status.** We'll keep `failed` meaning "a run in it failed": it's
   derived and exact, and a threshold would hide real failures. Instead,
   `failed_pct` becomes queryable: `top_q=failed_pct >= 5` on the Outer runs
   page (and a "≥ N% failed" chip) finds the trees that really broke. Until
   then, sort by `job:failed_pct`.
2. **Row rollup.** Planned: `job_agg=median&job_agg_by=children` gives the
   median of each date's best (or, with `job_agg_value=own`, of each date's own
   logged metric, never mixed), plus `best10 (p90)` / `worst10 (p10)` tails,
   a default in settings, and sorting by it. Team views can give each kind of
   training its own aggregate.

   Questions first:
   - **Q1.** To build the per-date rollup we need to know how a training's
     runs are laid out. Under one training, is each trade date its own run,
     with that date's trials as its children (training → date → trials)? Or
     do the trials sit directly under the training with the date as a param,
     like `params.trade_date`? Is it the same layout across all walk-forward
     trainings?
   - **Q2.** If a date is its own run, does it log its own metric (for
     example the out-of-sample score of the trial it selected), and under
     what name? You'll choose whether a row aggregates each date's own metric
     or its best trial. We never mix the two: a date without its own metric
     shows as missing.
   - **Q3.** The plan shows the chosen aggregate on top-level training rows
     only. When you expand a training, would you want each date row to show
     an aggregate over its trials as well (for example the median trial)?
     That is the "median over trials" number, not "median of date bests", so
     it means something different from the training row above it. Would it
     help you, or confuse things?
3. **Cold group-by.** Noted. Grouped views saved as *team* views can be
   warmed (personal ones live in your browser); we'll schedule it.
4. **Stuck vs lost.** Both counts are right: lost runs are stuck runs under an
   outer run that ended. `q=status = "stuck" and settled != "lost"` gives the
   902; the docs will say so.
5. **Empty results.** `kind` is a built-in field (the row's kind), hence 0;
   use `tags.kind`. We'll add a "did you mean tags.kind?" hint, and the API
   will refuse web-only params like `view=` with a pointer to `top=jobs`/`q=`.
6. **`prune -v`.** A bug on our side: the registry will be read in parallel,
   once per call.
7. **boto3.** A bug: the server will refuse to start on an S3 store without
   the `s3` extra.

Docs: the API table gets full paths, and the GIL advice is reversed per your
numbers (and ours). Thanks for the 3.15t measurements.
