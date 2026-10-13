# Plan 22: a flat board with Group by (runs grouped by a link or a field)

> Today the leaderboard shows the parent tree: outer runs are rows, and you fold them
> open to see their inner runs. An outer row mostly holds `–` (an orchestrator or sweep
> logs few metrics). Its inner runs are hidden until you open it, then fetched and paged
> one outer at a time, and filters act oddly on them. The inner counts need five columns
> that squeeze everything else. W&B instead lists the runs themselves and lets you
> group them by any field, with each group a collapsible header carrying aggregates.
>
> vmn records more than a parent: a run can point at the run that launched it
> (`parent`), the one it forked from (`forked_from`), the one it reruns (`rerun_of`), and
> the code state it was built from (`code_verstr`). "Outer" is not a kind of run. It is
> the name for a run that others point at with `parent`. So this plan makes the board a
> flat list of runs, and **Group by** offers every link alongside branch, status, tags
> and params. Grouping by a link makes the target run the group header.
>
> Paths are relative to `packages/vmn-exp/webui/src/` unless they start with
> `packages/`, `ui/` (= `packages/vmn-exp/src/vmn_exp/ui/`) or `docs/`.

Status: **done** (2026-10-13). Done: S1, S2 (no SQL cache serves the list, so
nothing to fall back from), W1, W2, W3 (group selection, Compare, Charts by group, the
plan-20 Compare redirects removed), W4 (phone section labels), D1. Not built: G6's
`5 of 16` on a header the filter cut (counts cover the passing rows only).

Sources: the 2026-10-13 discussion. Plan 20 C2 merged the inner counts into one cell, the
user reverted that to five columns (`ba6e87e0`), then asked whether the inner/outer
approach is right or W&B's is better. The answer was to keep the model and change the
presentation, and the user noted that an outer run is just one type of link between
runs.

## 0. What stays

- **The records.** `parent` (explicit or from `VMN_EXPERIMENT_ID`), `forked_from`,
  `rerun_of`, `code_verstr`, `kind`, `children`, and `tree_status` with the D12 rollup.
  Nothing is migrated and no record changes.
- **The run page.** Fleet/sweep table, parallel coordinates, Changes, the tree pill
  (`succeeded · 16/16 inner`, `16/20 · incomplete`), lineage.
- **CLI and SDK.** `vmn-exp list` keeps its tree view; `list_runs` is unchanged.
- **Status rollup.** The sidebar, attention strip and `experiments-status` keep counting
  as today.

## 1. Decisions

**G1. The board is a flat list of runs.** Every run is a row: single, inner, and the
runs others point at, outers included. No kind is hidden, and an orchestrator that logs
an ensemble score is an ordinary row. The fold arrow on rows, the five inner count
columns and the experiment cell's "N inner" go away. The subtitle stays
`N runs · M incl. inner`.

**G2. Group by.** A `Group by ▾` control sits next to `Columns`, in two sections:
- **Links:** `parent run`, `forked from`, `rerun of`, `same code`.
- **Fields:** `branch`, `status`, `tags.<key>`, `params.<key>` (keys from facets; a
  param is offered only when it has <= 20 distinct values).

Plus `none`. The default is `parent run` when the app has runs with a parent, else
`none`. The URL is `?group=parent|forked_from|rerun_of|code_verstr|branch|status|tags.<k>|params.<k>`,
absent = the default. Saved views keep it. One level only; nesting is out of scope, see §5.

**G3. What a link group is.** Grouping by link *L* puts each run in the group of the run
it points at with *L*. The target run is the group header, not also a row in that
group:
- `parent`: header = the outer run, members = its direct inner runs. A run with no
  parent is its own row in the `(no parent run)` group. That group's header has no run
  and is shown last, with its rows inline, not folded.
- `forked_from`: header = the source run, members = its forks.
- `rerun_of`: header = the original, members = its reruns. The original's own values
  count in the aggregates, so the group answers "how stable is this result".
- `code_verstr`: header = the code state (`0.1.0-dev.e71c74d.ba02c10`, its base version
  and branch; no run), members = every run built from it, so same-code runs with other
  params sit together.

A run that is itself a target and also a member elsewhere (an inner outer, a fork of a
fork) shows as a header in its own group and as a row in its target's group. The tree
is one level per screen. Lineage (`inputs`) is not offered, since one run can use many
inputs, so groups would overlap. It stays on the run page.

**G4. Group header rows.** A header row spans the table:
- fold chevron, the label (link groups: `@N name` linking to the target run, plus its
  status or tree pill; `same code`: the verstr; fields: `branch = main`);
- the status count `16 · 2 running · 1 failed` in colour, with text, as one cell;
- per visible metric column, the group's aggregate (G10). For a link group whose
  target run logged that metric itself, its own value shows on a second line `own 0.91`.

Groups open by default up to 10 rows each. A `+N more` row loads the rest.
`?collapse=<group key>` remembers closed groups.

**G5. Sorting and paging act on groups when grouped.** The sort column orders groups by
their aggregate, and rows within a group by their own value. With `group=none` the
board sorts and pages rows exactly as today. Paging pages groups (50 per page), and
rows within a group page on their own.

**G6. Filters apply to rows; groups follow.** A query, status chip or branch filter
selects rows. A group shows when any of its rows passes, and its counts and aggregates
are over the passing rows. The header says `5 of 16` when the filter cut it. The header
of a link group shows even when its target run fails the filter, since it names the
group.

**G7. Selection and Compare.** Checking a group header selects its loaded rows (the
header checkbox shows indeterminate when partial). Compare, Archive and the Charts tab
work on the selected rows. The Charts tab colours by group when grouped.

**G8. No compatibility layer.** User decision (2026-10-13): "if you need to deprecate
something - do it! we have no real users". Nothing old is mapped, redirected or kept
readable:
- `expand=`/`collapse=`-as-outer-ids from plan 20 and the count-column keys (`c:total`,
  `c:waiting`, `c:running`, `c:done`, `c:failed`, `c:inner`) are deleted, not ignored
  through a shim. An unknown URL key simply has no effect.
- Saved views from before this plan are not migrated; a saved view only knows the new
  keys.
- Code that existed only for the fold (useInnerRuns, util/sweepTree.ts fold state,
  innerRunColumns.ts, innerRows.css, the inner indent, the pending inner row) is
  deleted with its tests.
- Plan 20's old-page redirects (`overlay?runs=`, `compare?v=&to=`,
  `pages/Compare/legacyRedirects.tsx` and its routes) go too; anything vmn itself prints
  or links (CLI output, reports, docs) points at `compare-runs?tab=…` instead.
- Server-side, a list option or helper only the fold used goes with it.

**G9. Phone (< 640px).** Group headers become a sticky section label above their cards,
showing the status count and the group's aggregate on the primary metric. Cards are
unchanged.

**G10. The aggregate is mean by default and configurable.** User decision (2026-10-13):
"let it be mean but configurable to best or whatever else". The choices are `mean`
(default), `best`, `median`, `min` and `max`. `best` follows D1: the goal's direction
(min for `goal: min`, max for `goal: max`). A goal-less metric has no best, so it shows
the mean, marked `mean` in the cell title. The choice is set:
- per board, in the Group by menu, kept in the URL as `?agg=` and in saved views;
- per app default, in conf `experiment.ui.group_aggregate` (the board's default when the
  URL has no `agg=`).

The header cell names the aggregate in its title (`mean of 16`), and the column header
shows a small `mean`/`best`/… tag while grouped.

## 2. Contracts

**K1. `GET .../experiments?group=<field>`.** With `group`, the list answers with groups
instead of a flat page:
```
{ "groups": [ { "key": "...", "label": "...",
                "target": {verstr, idx, name, status, tree_status, metrics} | null,
                "counts": {total, running, waiting, done, failed, stuck},
                "aggregates": {"<metric>": {mean, best, median, min, max, n}},
                "rows": [ ...first N rows by the sort... ], "rows_total": 16 } ],
  "total_groups": 3, "total_rows": 48 }
```
`target` is set for the link groups `parent`/`forked_from`/`rerun_of`. It is null for
`code_verstr` (its label is the verstr) and for field groups. The paging parameters are:
- `offset`/`limit` page groups;
- `rows_per_group` (default 10, <= 100) caps each group's `rows`;
- `group_key=<key>&offset=&limit=` pages one group's rows (the `+N more` row).

`agg=mean|best|median|min|max` (default: conf `experiment.ui.group_aggregate`, else
`mean`) picks the aggregate that sorts groups (G5); every aggregate is in the payload so
switching needs no refetch. `best` is null for a goal-less metric. Finite values only;
`n` counts them. `sort`/`order`/`status`/`q`/`archived` behave as in G5/G6. Unknown
fields or aggregates give 400.
Rows with no value go to one `(none)` group, last (for `parent`: `(no parent run)`). A
link whose target is not in the index (pruned, another app) groups under the target's
verstr, with `target: null` and the label `<verstr> (not found)`.

**K2. Cost.** The grouping is built from the lock-free index snapshot, like `ordered`.
It is cached per (snapshot token, schema, group, filters, sort) in `LeaderboardCache`,
moved forward by deltas like `_Static`. Parent counts reuse `leaderboard_tree`'s
per-parent tallies; the other links tally the same way from the row fields. Target: a
grouped page at 100k runs answers in the same order of time as an ungrouped one (bench
in `packages/vmn-exp/tests/`, `@pytest.mark.serial`).

**K3. Server caches.** The SQLite/Postgres server caches (`cache_pg.py`,
`query_sql.py`) either implement K1 or fall back to the in-memory path, the way they
handle any other unsupported list option today. Both give the same answer (one
parametrised test over the backends).

## 3. Work units

Each unit is test-first: a pytest or vitest test is written red, then the minimum code
makes it green.

**S1. Grouped list endpoint** (K1, K2). `ui/leaderboard_groups.py` (new) +
`routes_leaderboard.py`.
- Tests: groups by each link and by branch and a param; a target is a header and not a
  member of its own group; a member that is also a target appears in both places;
  `(no parent run)` last; a missing target (`not found`); counts equal the rows';
  aggregates (mean, best by goal, median, min, max, n) follow the summary policy;
  `agg=` picks the sorting aggregate; the conf default; a target's own value; filters cut rows
  and keep link headers (G6); sort orders groups by aggregate and rows within;
  `group_key` paging; unknown field 400; a bench.

**S2. Server caches** (K3). Fallback or implementation, plus a parity test.

**W1. Group by control + URL** (G2, G8). `components/GroupByMenu.tsx`,
`hooks/useLeaderboardView` (`group`, `aggregate`, `collapse`).
- Tests: the two sections; default `parent` with parented runs and `none` without; the
  aggregate switch (default mean, `?agg=`, the app's conf default); URL round-trip; saved
  views keep it; the param option is hidden for > 20 values. No `expand=` mapping (G8).

**W2. Flat rows + group header rows** (G1, G4, G5). `pages/LeaderboardGroupRow.tsx`
(+ CSS); the virtualised table renders headers and rows from the grouped payload.
- Tests: every kind is a row with `group=none`; header content per group kind
  (run target, code state, field); aggregates and `own` per column; fold and
  `+N more`; sorting by a column orders groups; screen readers get the header as a
  row with its counts in words.
- Remove the five count columns, `useInnerRuns`, the fold toggle on rows, the "N inner"
  cell text and `sweepTree` fold state, along with their tests. A test may go only with
  the mechanism it pins, and only when a W2 test covers the outcome.

**W3. Selection, Compare, Charts** (G7).
- Tests: a header checkbox selects its loaded rows, is indeterminate when partial;
  Compare (N) counts rows; the Charts tab colours by group.
- Delete the plan-20 Compare redirects (G8) and repoint every vmn-made link at
  `compare-runs?tab=…`.

**W4. Phone** (G9).
- Tests at 390px: the sticky section label, its count, no horizontal scroll.

**D1. Docs.** `CLAUDE.md` (`vmn-exp ui` line: `group=`, `agg=`; the conf key
`experiment.ui.group_aggregate`), `docs/vmn-exp/ui.md`,
`docs/vmn-exp/ai-fleet-tracking.md` (where fleets show on the board), the plan-20 C2
note, and this plan's row in `docs/plans/README.md`.

## 4. Sequencing

| Wave | Units (parallel worktrees) | Depends on |
|---|---|---|
| 1 | S1 · W1 (against a mocked K1) | — |
| 2 | S2 · W2 | S1, W1 |
| 3 | W3 · W4 · D1 | W2 |

After each wave: `/simplify`, rebuild the bundle, light/dark screenshots at 1440 and
390. Only targeted Python tests per unit, plus the whole web suite once per merge.

## 5. Out of scope / open questions

- **Nested grouping** (group by parent, then by `params.lr`). W&B has it. One level
  covers sweeps, fleets, forks and reruns; revisit after use.
- **Grouping in the CLI** (`vmn-exp list --group`). It can come later on top of
  `leaderboard_groups.py`.
- **Lineage groups.** Grouping by an input would put a run in several groups. If it is
  wanted, it is a filter ("runs that used X"), not a grouping.
