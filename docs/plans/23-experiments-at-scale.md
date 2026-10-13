# Plan 23: the experiments screen at production scale (jobs with thousands of runs)

> In practice one outer run launches **thousands** of inner runs: a sweep, a k-fold ×
> seeds grid, an eval fan-out, a fleet of pods. The current screen was built for outers
> with ~16 inners and breaks at that size:
>
> - **The board.** Plan 22 G1 made every run a row. With 50 jobs × 2000 inners, the 50
>   things a person launched sit under 100,000 rows. Grouping by parent shows 10 rows a
>   group and `+N more`, and nobody pages 2000 runs through `+N more`.
> - **The run page.** Its Fleet card lists only the first 50 children
>   (`core/tree.py:FLEET_MAX_CHILDREN_DETAIL`), with no paging, sorting or filtering of
>   the rest. Each poll reads every descendant's state (`fleet_summary`,
>   `subtree_status`) before it can answer 304.
> - **The sweep card.** `.../sweep` returns every trial, unpaged, on every poll.
> - **Scoping.** Facets cannot be scoped to one job. The query language has
>   `parent = "<v>"` for direct children only, and nothing for a subtree.
> - **Bulk actions.** These work on explicit verstr lists capped at 500 ("select all" =
>   the first 500), so "archive the 312 failed runs of this job" can't be done.
> - **Live updates.** Every open tab polls every 5-15 s, and each poll re-fetches page 1
>   plus every running or visible row.
> - **Answers.** Nothing shows how far along a job is, how fast it is going, when it will
>   end, what its best run is, how its metric is distributed, or why its runs fail.
>   Those are the questions a person running thousands of runs asks first.
>
> This plan makes the **job** (a run other runs point at with `parent`) the unit of the
> experiments screen. It has an index of jobs, and a job page that answers those
> questions from server-side rollups in O(1). The job page also has a full run table
> scoped to its subtree, failure clusters, and charts that stay fast at 10k points. It
> keeps plan 22's flat list and Group by as the "All runs" view.
>
> Paths are relative to `packages/vmn-exp/webui/src/` unless they start with
> `packages/`, `ui/` (= `packages/vmn-exp/src/vmn_exp/ui/`), `core/`
> (= `packages/vmn-exp-sdk/src/vmn_exp/core/`) or `docs/`.

Status: **in progress** (2026-10-14).

Sources: the 2026-10-13 discussion. The user's words: "in reality we will have
thousands of inners per outer run; the current ui is very basic and does not meet any
real production needs". The UI's limits are inventoried in §1.

## 0. What stays

- **The records.** `parent`, `kind`, `children`, `tree_status` (the D12 rollup),
  `sweep_planned`, `expected_pods`, `status_fields`. No record format change and no
  migration. Everything new is derived in the index.
- **The flat list with Group by** (plan 22), as the **All runs** view (W1).
- **The run page** of a single run (curves, Changes, failure context, lineage). An
  inner's run page gains job context (W7).
- **Copy-first actions** (plan 20 D8). The UI shows the command for rerun, restore or
  prune and never runs it itself. Only archive, tag and note mutate, as today.
- **Storage is the source of truth.** Rollups are index state, rebuildable, never written
  to the store.

## 1. What breaks today (inventory, 2026-10-13)

| Surface | Today | At 5000 inners per outer |
|---|---|---|
| Board, `group=parent` | 50 groups × 10 rows, `+N more` per group (`routes_leaderboard.py:37-39`) | 500 clicks to see one job's runs |
| Board, flat | every run a row | jobs buried under inners |
| Run detail `fleet` | counts over all children; detail rows for the first 50 only (`core/tree.py:287,304`) | 4950 runs unreachable from the job |
| Run detail cost | `subtree_status` and `fleet_summary` read every descendant's state per request, and the ETag comes after the body (`readers/experiment_detail.py:149-164`) | O(subtree) per 5 s poll per tab |
| `.../sweep` | all trials, unpaged; claims listed from storage per request (`routes_sweep.py:31-41`) | multi-MB payload per poll |
| Facets | `archived` only, no `q`/scope (`routes_leaderboard.py:135`); distinct cap 20 | no "values of `lr` within this job" |
| Query | `parent = "<v>"` (direct children) | no subtree, no "under job X" |
| Bulk | verstr lists ≤ 500 (`useBoardSelection.ts:8`, `jobs_exp_meta.py:12`) | can't act on "all failed in this job" |
| Series | ≤ 200 runs, 200k points a POST (`routes_series.py:36,100`) | fine for top-K, not for "all" (and "all" is never what a person wants) |
| Live | polling page 1 + running/visible rows (`leaderboardRefresh.ts`) | heavy, and rows jump under the reader |
| Failure info | `error_summary`/`end_reason`/`exit_code`/`signal` on rows (queryable); `output_tail` in detail only | no "why do they fail", only per-run |

What already scales and is reused: the index's per-generation deltas
(`ui/leaderboard_cache.py`), per-parent tallies (`ui/leaderboard_tree.py`), early-ETag
list/columns/importance with an LRU of bodies, the virtualized table, and the columnar
metric store with LOD (plan 12).

## 2. Design principles

1. **Answer first, rows second.** A job page opens on its answers: progress, ETA,
   best, distribution, failures. Rows come after, for whoever needs them. Thousands of
   rows are a list to query, not one to read.
2. **Aggregates are server-side and O(1) per request.** Every number on a job's
   overview comes from a rollup the index keeps up to date by deltas, like the
   per-parent tallies today. No request reads a subtree.
3. **Scope is a first-class parameter, not a query hack.** `scope=<verstr>` (the
   subtree) works the same way on the list, columns, facets, importance, failures,
   series selection and bulk actions.
4. **Selection is a query, not a list of ids.** "All 312 failed runs in this job" is
   `scope + q`, resolved on the server with a count preview. The 500 cap goes away.
5. **Live without jank.** The server pushes "something changed" (SSE), and the client
   revalidates with ETags. Rows never move under the reader: new or re-sorted rows
   show as a `12 new · show` bar, as Linear/Gmail do. Counts and the progress bar move
   live.
6. **Stable paging.** Live data plus offset paging duplicates and skips rows, so pages
   use a keyset cursor (sort value + verstr).
7. **Density is a choice.** Compact rows (28 px, one line) for scanning thousands,
   comfortable (today's two-line rows) for reading. The choice is remembered.
8. **Everything is a URL.** Tab, scope, filters, sort, columns, chart, cluster and
   density are all in the URL, so saved views work per job and per app.
9. **Performance budgets are tests** (§6), at 100k runs with jobs of 5000.

## 3. Information architecture

```
App ─┬─ Experiments (index)
     │    ├─ Jobs view (default): one row per top-level run (jobs + single runs)
     │    └─ All runs view: plan 22 flat list + Group by
     │
     └─ Run page
          ├─ a job (has children) → Job page: Overview · Runs · Charts · Failures · Code · Log
          └─ a single / inner run → today's run page + job context bar
```

### 3.1 Experiments index, Jobs view (default)

One row per **top-level** run (`depth = 0`): jobs and single runs. Inner runs are not
rows here. They are reached through their job, or through All runs.

A job row (compact density shown):

```
☐ @36  lr_layers_grid   ▕██████████░░░▏ 1,412/2,000 · 3 failed · 41/min · ETA 14m   val_loss 0.182 ↓ (@1,903)  ▁▂▅█▅▂  main · 2h ago
☐ @24  kfold-cv         ▕████████████▏ 5/5 · 1 failed                               val_loss 0.377 ↓ (@27)     ─      main · 1d ago
☐ @54  live-training    ● running · step 41k/100k                                   loss 0.912                         main · 3m ago
```

- **Status** is the tree status pill (D12).
- **Progress** is a bar like F13's, plus `done/expected` (expected = `sweep_planned`,
  else `expected_pods`, else the children so far), the failure count, throughput
  (completions per minute over the last 10 min), and an ETA from that throughput. A
  single run shows its own step progress (`last_step`) instead.
- **Best** is the best inner on the primary goal metric, with the inner's `@N` as a
  link. A single run shows its own value.
- **Spread** is a sparkline histogram of the primary metric across the job's runs (from
  the rollup sketch). Hovering it shows p10 / median / p90.
- **Sort** works on any of these: progress, failure rate, best, throughput, started.
- **Filter.** The query applies to top-level rows, plus `has(…)` over the subtree (S2),
  e.g. "jobs with any run `val_loss < 0.2`".
- The attention strip (plan 20 C6) gains "2 jobs with > 5% failed", "1 job stalled
  (no completion in 10 min)".

### 3.2 Job page

Header (sticky): name, `@N`, tree status, the progress bar with counts, throughput, ETA,
`● live · updated 3s ago` with Pause, the CLI card (`vmn-exp list <app> --query
'parent = "…"'`), and the Reproduce menu (copy commands: rerun the failed ones, sweep
agent, prune).

**Overview tab** (default; everything from the rollup, so it's instant at any size):

- **KPI tiles:** done / expected, failed (% and count), running, waiting, stuck; median
  and p90 duration; best metric (linked).
- **Progress over time:** a stacked area of status counts per time bucket, with a
  completions-per-minute line. This is where a stall or a failure storm shows up.
- **Best-so-far:** the best goal metric by completion order (sweeps converge, or they
  don't).
- **Metric distribution:** a histogram of the primary metric (choosable), with the job's
  previous attempt or the parent baseline overlaid as an outline when one exists
  (plan 20 `baselines`).
- **Top 10 runs** on the goal metric (a mini table, links), plus "show all in Runs".
- **Failure clusters, top 3** (W5), each with a count and a link to the Failures tab.
- **Params that matter** (sweeps): the importance bars (existing
  `experiments-importance`, scoped).

**Runs tab:** the plan-22 table scoped to the subtree (`scope=`), with every board
feature (query bar, sort, columns, density, keyboard, saved views), plus:

- **A facet sidebar.** Status counts, and per param its value counts (a mini histogram
  for numeric params), each clickable as a filter token. Facets are scoped and
  filter-aware, so they show counts after the other filters.
- **Group by param** within the job (plan 22's grouped endpoint, scoped). A typical use
  is `fold` × `seed`, comparing aggregate rows.
- **Selection by query.** The header checkbox selects "all 312 matching" (scope + q),
  not the loaded rows. Archive/tag act through S4 with a count confirm.
- **Keyset paging and the `N new` bar** (W6).

**Charts tab** (scoped, canvas-rendered, downsampled server-side):

- Param vs metric scatter, with every point up to 50k and colour by a param or status.
- Parallel coordinates: brushing filters the Runs tab.
- Overlaid curves for the top-K (default 20) or the selected runs, within the series
  caps.
- Metric histogram / box by a param value.

**Failures tab** (W5):

- Clusters by **failure signature**. The signature normalizes `end_reason`, `signal`,
  `exit_code` and `error_summary`: numbers, hex, paths and verstrs are masked, so
  `CUDA out of memory. Tried to allocate 2.31 GiB` and `... 1.07 GiB` are one cluster.
- Per cluster: the count, the share of failures, first/last seen, top hosts, the
  params overrepresented in it (`batch_size = 512` in 94% of the cluster vs 25% of the
  job), and one example run's `output_tail`.
- Actions: filter the Runs tab to the cluster, copy the "rerun these" command, archive
  the cluster (S4).

**Code / Log tabs:** the outer's own Changes card and log, as today.

### 3.3 Inner run page

- **A job context bar** under the header: `Job lr_layers_grid › run 1,903 of 2,000 ·
  rank 1 of 1,409 on val_loss · ‹ prev  next ›`. Prev/next follow the order of the Runs
  tab the user came from (carried in the URL).
- **Peers.** The run's metric is marked on the job's distribution histogram, so its
  place among its peers is visible at a glance.

### 3.4 Group by in each view

A Group by groups the rows of the view it is in (one control, `group=`, as in plan 22):

| View | Its rows | Grouped by `branch` / `status` / `tags.<k>` / `params.<k>` |
|---|---|---|
| Jobs | jobs and single runs | groups of **jobs**: `main · 14 jobs · 31,000 runs · 2 jobs failing`. The header sums the jobs' rollups (runs, failures, best). `params.<k>` is the job's own params (`model = llama-8b`). |
| All runs | every run, inner runs included | groups of **runs across jobs**: `params.lr = 0.01 · 8,400 runs from 6 jobs · mean val_loss 0.21`. This compares a setting across jobs. |
| A job's Runs tab | the job's subtree | groups **inside the job**: `fold`, `seed`, `status`, `host`, failure signature. |

Two rules change at this scale:

- **A big group opens as a filter, not through `+N more`.** The header carries the
  answer: counts, the run bar, and mean/best/median per metric (plan 22's aggregates).
  Up to 50 runs, a group still unfolds in place. Past that, its header has no fold:
  clicking it applies the group's clause as a filter token (`params.lr = 0.01`) in the
  same view, ungrouped, with the full table, facets and charts. In the Jobs view,
  clicking a group of jobs filters the Jobs list. A job row itself opens its job page.
- **Group by parent run is the Jobs view.** In All runs, "parent run" in the Group by
  menu switches to the Jobs view (`view=jobs`, keeping the filters), instead of
  rendering a group per job over 100k rows. The other links (forked from, rerun of,
  same code) group as in plan 22.

For a value that varies between a job's runs, group either in All runs (across jobs) or
in the job's Runs tab (inside one job). Grouping two levels at once (job × `lr` in one
table) is out of scope (§9).

### 3.5 Search across every run

Search always covers **all runs of the app** (100k+), whatever view is open. A view
changes how results are shown, never what is found.

- **What it matches:**
  - name, verstr (prefix), `@N`, note and tags
  - param values, command, branch and author
  - `error_summary` / failure signature, and intent text
  - The same box takes the query grammar (`val_loss < 0.2 and params.lr = 0.01`), as
    today.
- **Jobs view.** The list narrows to the jobs that match themselves or have matching
  runs (`has(…)`, S2). Each job carries a chip `412 matching runs`, which opens its Runs
  tab with the search applied. Single runs that match show as rows. A result line above
  the list reads `3 jobs · 412 runs match · show all 412 runs`, and the last part
  switches to All runs with the search kept. Inner hits are never hidden.
- **All runs.** The flat (or grouped) list of matching runs, as today.
- **Job page.** Search is scoped to the job, with a `search all runs` link that drops the
  scope.
- **⌘K "go to run"** finds any run by `@N`, name, verstr prefix, tag or note. It returns
  the top 20 as you type, each with its job (`@1,903 lr_layers_grid-t1903 · in
  lr_layers_grid`), and Enter opens it.
- **Budget:** a search over 100k runs answers in ≤ 100 ms server-side; ⌘K results in ≤ 50
  ms (§6).

## 4. Server work

**S1. Index: ancestry + per-job rollup** (`ui/leaderboard_tree.py` grows into
`ui/job_rollup.py`).
- Every row gets `root` (its top-level ancestor) and `ancestors` (short; depth is small),
  maintained when `parent` links arrive.
- Per job (any run with children), over its **subtree**, a rollup maintained by deltas
  (a changed run updates its ancestors' rollups in O(depth)):
  - Status counts (the D12 states), `expected`, first `started_at`, last `finished_at`.
  - Completions per 1-minute bucket, kept for 24 h then per 10 min. Throughput and ETA
    come from these.
  - Per declared-goal metric (plus the primary): n, min, max, sum, the best verstr, and a
    fixed-size quantile sketch (t-digest or a DDSketch-style log histogram, ≤ 2 KB,
    mergeable, removable via counts). This feeds the sparkline, histogram and p10/p90.
  - Duration sketch.
  - Failure-signature counts (S3).
- Removal: a run leaving (pruned, archived when archived is hidden) is subtracted.
  Min/max/best fall back to a lazy recompute flagged per job, bounded by one subtree
  scan per generation per job.
- Memory budget: ≤ 4 KB per job + 16 bytes per row. Bench: 100k runs / 20 jobs × 5000:
  a generation with 500 changed runs costs ≤ 2× today's.

**S2. Scope everywhere.**
- `scope=<verstr>` on `experiments` (flat and grouped), `experiments-columns`,
  `experiments-facets` (which also gains `q`/`status`), `experiments-importance`,
  `failures`, and the bulk actions. It means the verstr's subtree, without the verstr
  itself.
- `top=1` restricts the list to `depth = 0` (the Jobs view).
- Query additions: `under("<v>")` (subtree membership) and `has(<expr>)` on a job row
  (true if any subtree run matches; evaluated from an inverted index of `root`, and
  capped by the scope size).
- Jobs-view rows carry the rollup's summary fields (`progress`, `failed_pct`,
  `throughput`, `eta_sec`, `best`, `spread`) as sortable, queryable row fields.

**S3. Job endpoints** (all keyed on an early ETag of index generation + live bucket +
params, so a poll answers 304 before building anything):
- `GET .../experiments/{v}/summary`: the rollup (counts, KPIs, sketches as histogram
  bins, best, top 10).
- `GET .../experiments/{v}/timeline?bucket=`: status counts and completions over time.
- `GET .../experiments/{v}/failures`: clusters (signature, count, first/last, hosts,
  overrepresented params, example verstr). The signature is computed at index time from
  row fields (`core/failure_signature.py`, pure).
- Run detail of a job drops `fleet.children` and the O(subtree) `subtree_status` read.
  The tree status and counts come from the rollup.
- `.../sweep` becomes the spec plus progress from the rollup. Its trials table is the
  scoped Runs tab, so the unpaged list is removed.

**S4. Bulk actions by query.** `POST .../actions/exp_archive` (and `exp_tag`, new
multi-run) takes `{scope, q, status}` or `{verstrs}`.
- `dry_run: true` returns `{count, sample}`.
- Execution runs as a job (the existing actions/jobs machinery) in batches of 500 with
  progress, and is idempotent.
- The UI confirms with the count.

**S5. Live push.** `GET .../events?scope=<v>|top` is SSE. It emits `{generation,
changed: {rows, jobs}}` at most once per second per stream (coalesced), plus a heartbeat
every 25 s. The client revalidates whatever is on screen with its ETags. It falls back to
today's polling when SSE fails (proxies), and is served by the background refresher.

**S6. Keyset paging.** `cursor=<opaque>` on `experiments` (sort value + verstr) next to
`offset`. Rows that moved are reported through S5 and the `N new` bar instead of
shifting the page.

**S7. Grouping per view.**
- The grouped list takes `top=1` (Jobs view: groups of top-level rows, aggregates
  merged from the jobs' rollups: run counts summed, sketches merged, best of bests)
  and `scope=` (a job's Runs tab).
- Each group carries `rows_total`, so the client knows whether it may unfold (≤ 50) or
  opens as a filter, and `clause` (the filter text for the group, e.g.
  `params.lr = 0.01`, `branch = "main"`, with `= null` for the no-value group).
- `group=parent` without `top=1` is still served for the API, but the board no longer
  asks for it.

**S8. A search index over all runs** (`ui/search_index.py`).
- Per snapshot: an inverted index of tokens and trigrams over the §3.5 fields, kept up
  to date by deltas like the facets. Substring (`~`) and the free-text search use it
  instead of a scan.
- `GET .../search?text=&limit=20`: ⌘K results with each run's job (`root`) and rank.
- The list's text search returns `{jobs_matched, runs_matched}` with the Jobs view, and
  a per-job `matched` count for the chip.
- Memory ≤ 150 B per run.

## 5. Web work

**W1. Experiments index: Jobs | All runs** (`pages/Leaderboard.tsx` splits into
`pages/Experiments/{JobsView,AllRunsView}.tsx`).
- Jobs is the default. `view=all` gives plan 22's board, where `group=` still applies.
- The job row (§3.1): `components/JobProgress.tsx` (the bar + counts + throughput +
  ETA, one component reused on the job header, cards and F13's group headers, and the
  run page's Fleet card retires), plus `Sparkline`.

**W2. Job page shell + Overview** (`pages/Job/`).
- Routed by the run route when the run has children. Tabs are in the URL (`tab=`).
- Overview tiles and charts come from S3 summary/timeline.

**W3. Runs tab.** `LeaderboardTable` scoped to the job, plus `components/FacetSidebar.tsx`
(scoped facets, tokens into the filter grammar), selection by query (S4), and
Group by within the job.

**W4. Charts tab.** Canvas scatter and parallel coordinates fed by
`experiments-columns?scope=` (≤ 50k points), and overlay curves from `POST series`
(top-K / selection). The brush writes `q`.

**W5. Failures tab.** Clusters from S3. A cluster click filters Runs
(`q=failure_sig = "…"`).

**W6. Live and paging.** `hooks/useLiveScope.ts` (SSE, polling fallback), keyset paging,
and the `N new · show` bar. Counts and progress update in place, while rows wait for
the user.

**W7. Inner run page context.** The job context bar, rank, prev/next, and the peers
histogram marker.

**W8. Density and keyboard.**
- Compact/comfortable toggle (`density=`), remembered per user.
- Keys: `j/k` move, `x` select, `shift+x` range, `Enter` open, `/` filter, `g j` jobs,
  `g a` all runs, `[ ]` prev/next run on a run page.
- ⌘K gains "go to job".

**W10. Group by per view** (§3.4).
- The Group by menu is the same component in all three views. Its field list comes from
  the view's facets (job params in Jobs, all params in All runs, scoped facets in a
  job).
- A group over 50 runs renders without a fold: its header is a button that adds
  `clause` as a filter token and drops `group=`. Back restores the grouped view.
- In All runs, picking "parent run" navigates to `view=jobs` with the filters kept.

**W11. Search everywhere** (§3.5). The filter box keeps its grammar.
- The Jobs view gets the result line, the `N matching runs` chip, and the switch to All
  runs.
- The job page gets `search all runs`.
- ⌘K "go to run" uses S8.

**W9. Retire.**
- The Fleet card's 50-row table and the sweep card's trial table: the Runs tab
  replaces both.
- `+N more` paging into big groups: over 50 runs a group opens as a filter (W10).
  `+N more` stays only for groups of ≤ 50 runs.
- The 500 select-all cap.

## 6. Performance budgets (tests, `@pytest.mark.serial` benches + uiload profile)

Fixture: 100k runs = 20 jobs × 5000 inners. 200 live inners per job (4000 live), plus
10k singles.

| Measure | Budget |
|---|---|
| Jobs view page (50 rows), server, warm | p95 ≤ 50 ms |
| Job summary / timeline / failures, warm, 304 path | p95 ≤ 5 ms / ≤ 20 ms built |
| Scoped Runs page (200 rows), any sort | p95 ≤ 80 ms |
| Scoped facets | p95 ≤ 100 ms |
| Text search over 100k runs (list, Jobs view counts) | p95 ≤ 100 ms |
| ⌘K "go to run" over 100k runs | p95 ≤ 50 ms |
| Columns for scatter, 5000 points | ≤ 150 ms, ≤ 400 KB gz |
| Index generation, 500 changed runs | ≤ 2× today's (`test_fix_ui_leaderboard_incremental_scale`) |
| Rollup memory | ≤ 4 KB/job + 16 B/row |
| Client: job page first paint (cached shell) | ≤ 1 s; scroll 5000 rows at 60 fps (no frame > 16 ms in the vitest render bench proxy) |
| Live: 20 open tabs on one job | server CPU ≤ today's single polling tab |

A new uiload profile, `jobs`, drives this with real job processes. The existing `load`
profile stays.

## 7. Work units and order

Each unit is test-first (pytest/vitest red, then green), one worktree each, ≤ ~300 lines
a file.

1. **B0** bench fixtures + baselines (the §6 table measured on today's code).
2. **S1** ancestry + rollup → **S2** scope/top/query → **S3** endpoints (sequential:
   each builds on the last).
3. In parallel after S2: **S4** bulk by query, **S5** SSE, **S6** keyset, **S7**
   grouping per view (after S1 for the merged rollups), **S8** search index.
4. Web in parallel once its endpoints exist:
   - W1 (needs S2)
   - W2 (S3)
   - W3 (S2, S4)
   - W4 (S2)
   - W5 (S3)
   - W6 (S5, S6)
   - W7 (S2)
   - W8 (none)
   - W10 (S7, after W1 and W3)
   - W11 (S8, after W1)
5. **W9** retire, then docs (ui.md, CLAUDE.md, the plans README row).

## 8. Decisions

Decided (2026-10-13):
- **Naming: "job".** The UI says job. A sweep is a job with a spec, badged `sweep`.
  "outer"/"inner" stay in the CLI and records.
- **Landing: the Jobs view**, with the last view remembered per app (`localStorage`;
  `view=` in the URL wins). Jobs scales with what people launch, not with what jobs fan
  out to; every inner is two clicks away (the job's Runs tab, or All runs), and an app
  with no jobs reads the same in both views.
- **Quantiles: approximate sketch.** About 1% rank error, O(1), mergeable. Best, min
  and max stay exact.

Open:
1. **SSE in standalone `vmn-exp ui` as well as server mode?** Recommended: yes, one code
   path, with polling as the fallback.
2. **Bulk archive by query:** allowed for the `member` role, or `admin` only past N runs
   (server mode)? Recommended: member, with the count confirm.

## 9. Out of scope

- Scheduling or launching runs from the UI (copy-first stays).
- Cross-job dashboards: that is reports (plan 13), which can embed the new job panels
  later.
- Two-level grouping (job × a param in one table, a pivot). Inside one job it is the
  Runs tab's Group by; across jobs it is All runs grouped by the param.
- Nested jobs deeper than one level get rollups (S1 is per subtree), but no special UI.
- Log search across thousands of runs' `output.log`. Failure clusters use row fields and
  one example tail.

## 10. API contract (phase 2, fixed 2026-10-14)

Server and web units build against this contract in parallel. Prefix:
`/api/v1/workspaces/{ws}/apps/{app}`. Rollup fields come from S1
(`ui/job_rollup*.py`, `LeaderboardCache.job_rollup/job_rollups`).

**Rows (S2).** Every board row gains:
- `root`: its top-level ancestor's verstr, or null for a top-level run.
- `failure_sig`: S1's `failure_signature.signature(row)`, null unless failed/stuck.

Both are query fields.

**Jobs view (S2):** `GET .../experiments?top=1&sort=&order=&q=&status=&offset=&limit=`.
- Rows are top-level runs only (`depth = 0`).
- A job row carries `job`, the compact summary: `{total, counts: {running, waiting,
  succeeded, failed, stuck}, done, expected, progress, failed_pct, throughput_per_min,
  eta_sec, metric, best, best_verstr, best_idx, spread: [12 counts]}`. A single run has
  `job: null`.
- Extra sort keys: `job:progress`, `job:failed_pct`, `job:throughput`, `job:best`
  (best-first by the metric's goal), `job:total`, `job:started`.
- `q`/`status` filter the top-level rows by their own fields; `q` may use `under` (S2)
  but not `has` (W11).

**Scope (S2):** `scope=<verstr>` on `experiments` (flat and grouped),
`experiments-columns`, `experiments-facets`, `experiments-importance`.
- It means the verstr's subtree, without the verstr itself. An unknown verstr gives 404.
- `experiments-facets` also takes `q` and `status`, so its counts follow the other
  filters.
- Query: `under("<v>")` is true for rows in v's subtree.

**Job summary (S3):** `GET .../experiments/{v}/summary`. It returns 404 if v has no
children, and an early ETag. The body is S1's `job_rollup` payload plus:
- `name`, `idx`, `status`, `tree_status`, `kind`, and `sweep: bool`.
- `top`: up to 10 rows on the main metric, as `{verstr, idx, name, status, value}`.
- `timeline`: `{bucket_sec, start, buckets: [{t, started, succeeded, failed}]}`. The
  buckets are per minute for the last 24 h (coarser beyond), and `running(t)` is derived
  client-side.

**Failures (S3):** `GET .../experiments/{v}/failures?limit=20`.
- Body: `{total_failed, clusters: [{sig, label, count, share, first_at, last_at, hosts:
  [{host, count}] (top 5), params: [{key, value, share, base_share}] (overrepresented,
  top 5), example_verstr}]}`.
- Early ETag, memoized per generation.

**Run detail of a job (S3).** `fleet.children` is dropped. `fleet.counts` and
`fleet.expected` stay, read from the rollup, and the detail no longer reads the subtree.
`.../sweep` keeps the spec and gets its trial counts from the rollup. Its `trials` array
is capped at the first 50, with a `trials_total`.

**Web routes (W1, W2).**
- `/ws/{ws}/app/{app}` is the Jobs view (`view=jobs` default; `view=all` is plan 22's
  board). The last view is remembered per app in localStorage, and the URL wins.
- A run with children opens the job page: `/ws/{ws}/app/{app}/run/{v}?tab=overview|runs|charts|failures|code|log`.
