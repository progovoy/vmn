# Plan 22: a flat board with Group by (outer runs become group headers)

> Today the leaderboard shows the run tree: outer runs are rows, and you fold them open
> to see their inner runs. An outer row mostly holds `–` (an orchestrator or sweep logs
> few metrics). Its inner runs are hidden until you open it, then fetched and paged one
> outer at a time, and filters act oddly on them. The inner counts need five columns
> that squeeze everything else. W&B instead lists the runs themselves and lets you
> group them by any field, with each group a collapsible header carrying aggregates.
> This plan keeps vmn's recorded parent links and tree status, and changes how the
> board presents them: a flat list of the runs you compare, plus **Group by**, where the
> outer run is one grouping among branch, tag and any param.
>
> Paths are relative to `packages/vmn-exp/webui/src/` unless they start with
> `packages/`, `ui/` (= `packages/vmn-exp/src/vmn_exp/ui/`) or `docs/`.

Status: **proposal** (2026-10-13).

Sources: the 2026-10-13 discussion. Plan 20 C2 merged the inner counts into one cell, the
user reverted that to five columns (`ba6e87e0`), then asked whether the inner/outer
approach is right or W&B's is better. The answer was to keep the model and change the
presentation.

## 0. What stays

- **The data model.** `parent` (explicit or from `VMN_EXPERIMENT_ID`), `kind`
  (`outer`/`inner`/`single`), `children`, and `tree_status` with the D12 rollup. Nothing
  is migrated and no record changes.
- **The outer run's own page.** Fleet/sweep table, parallel coordinates, Changes, and
  the tree pill (`succeeded · 16/16 inner`, `16/20 · incomplete`).
- **CLI and SDK.** `vmn-exp list` keeps its tree view; `list_runs` is unchanged.
- **Status rollup.** The sidebar, attention strip and `experiments-status` keep counting
  as today.

## 1. Decisions

**G1. The board lists comparable runs by default.** These are inner and single runs. An
outer run is a container, not a comparable run, so it is not a row in the flat view. The
subtitle stays `N runs · M incl. inner`, with outers counted on the side:
`48 runs · 3 sweeps`. A toggle `show outer runs` brings them back as plain rows, for
example an orchestrator that logged its own metrics.

**G2. Group by.** A `Group by ▾` control sits next to `Columns`. Its options are:
- `none` (default when the app has no outer runs);
- `parent run` (default when the app has outer runs);
- `branch`;
- `tags.<key>`;
- `params.<key>` (keys from facets; numeric params are bucketed only when they have
  <= 20 distinct values, otherwise the option is hidden);
- `status`.

The URL is `?group=parent|branch|status|tags.<k>|params.<k>`, absent = the default.
Saved views keep it. One level only. Nested grouping is out of scope, see §5.

**G3. Group header rows replace outer rows.** A header row spans the table:
- fold chevron, then the group's label (for `parent`: `@N name`, linking to the outer
  run's page, plus its tree pill; for others: `branch = main`);
- the status count `16 · 2 running · 1 failed` in colour, with text, as one cell. This
  is where the inner counters live, and the five count columns go away;
- per visible metric column, the group's aggregate. The default aggregate is best (goal
  metrics, D1) or mean (goal-less). A per-board `aggregate: best|mean|min|max` choice
  sits in the Group by menu.

Groups open by default up to 10 rows each. A `+N more` row loads the rest, as plan 20's
placeholder row does today. `?collapse=<group key>` remembers closed groups.

**G4. Sorting and paging act on groups when grouped.** The sort column orders groups by
their aggregate, and rows within a group by their own value. With `group=none` the
board sorts and pages rows exactly as today. Paging pages groups (50 per page), and
rows within a group page on their own.

**G5. Filters apply to rows; groups follow.** A query, status chip or branch filter
selects rows. A group shows when any of its rows passes, and its counts and aggregates
are over the passing rows. The header says `5 of 16` when the filter cut it. This fixes
today's "an opened outer shows every inner run whatever the filter says".

**G6. Selection and Compare.** Checking a group header selects its loaded rows (the
header checkbox shows indeterminate when partial). Compare, Archive and the charts tab
work on the selected rows. The Charts tab colours by group when grouped.

**G7. Old URLs.** `expand=` and `collapse=` from plan 20 map to `group=parent` with that
group open or closed. The removed count-column keys (`c:total`, `c:waiting`, `c:running`,
`c:done`, `c:failed`, `c:inner`) are ignored.

**G8. Phone (< 640px).** Group headers become a sticky section label above their cards,
showing the status count and the group's best value. Cards are unchanged.

## 2. Contracts

**K1. `GET .../experiments?group=<field>`.** With `group`, the list answers with groups
instead of a flat page:
```
{ "groups": [ { "key": "...", "label": "...", "outer": {verstr, idx, name, tree_status} | null,
                "counts": {total, running, waiting, done, failed, stuck},
                "aggregates": {"<metric>": {best, mean, min, max}},
                "rows": [ ...first N rows by the sort... ], "rows_total": 16 } ],
  "total_groups": 3, "total_rows": 48 }
```
The paging parameters are:
- `offset`/`limit` page groups;
- `rows_per_group` (default 10, <= 100) caps each group's `rows`;
- `group_key=<key>&offset=&limit=` pages one group's rows (the `+N more` row).

`sort`/`order`/`status`/`q`/`archived` behave as in G4/G5. Unknown fields give 400.
Rows with no value for the field go to one `(none)` group, last.

**K2. Cost.** The grouping is built from the lock-free index snapshot, like `ordered`.
It is cached per (snapshot token, schema, group, filters, sort) in `LeaderboardCache`,
moved forward by deltas like `_Static`, and its counts reuse `leaderboard_tree`'s
per-parent tallies. Target: a grouped page at 100k runs answers in the same order of
time as an ungrouped one (bench in `packages/vmn-exp/tests/`, `@pytest.mark.serial`).

**K3. Server caches.** The SQLite/Postgres server caches (`cache_pg.py`,
`query_sql.py`) either implement K1 or fall back to the in-memory path, the way they
handle any other unsupported list option today. Both give the same answer (one
parametrised test over the backends).

**K4. Flat view without outers.** `GET .../experiments?kinds=inner,single` (G1),
defaulting to all kinds for API compatibility. The board sends it.

## 3. Work units

Each unit is test-first: a pytest or vitest test is written red, then the minimum code
makes it green.

**S1. Grouped list endpoint** (K1, K2, K4). `ui/leaderboard_groups.py` (new) +
`routes_leaderboard.py`.
- Tests: groups by parent, branch and a param; counts equal the rows'; aggregates follow
  the summary policy and goal; `(none)` group last; filters cut rows and groups (G5);
  sort orders groups by aggregate and rows within; `group_key` paging; unknown field
  400; `kinds=` filter; a bench.

**S2. Server caches** (K3). Fallback or implementation, plus a parity test.

**W1. Group by control + URL** (G2, G7). `components/GroupByMenu.tsx`,
`hooks/useLeaderboardView` (`group`, `aggregate`, `collapse`).
- Tests: default `parent` with outers and `none` without; URL round-trip; saved views
  keep it; `expand=`/`collapse=` mapping; the param option hidden for > 20 values.

**W2. Group header rows** (G3, G4). `pages/LeaderboardGroupRow.tsx` (+ CSS), and the
virtualised table renders headers and rows from the grouped payload.
- Tests: header content per group kind; aggregates per column; fold and `+N more`;
  sorting by a column orders groups; screen readers get the header as a row with its
  counts in words.
- Remove the five count columns, `useInnerRuns`, the fold toggle on rows, and
  `sweepTree` fold state, along with their tests (a test may go only with the
  mechanism it pins, and only when a W2 test covers the outcome).

**W3. Selection, Compare, Charts** (G6).
- Tests: a header checkbox selects its loaded rows, is indeterminate when partial;
  Compare (N) counts rows; the Charts tab colours by group.

**W4. Flat view and outer toggle** (G1, K4).
- Tests: outers are absent by default and shown with the toggle; the subtitle counts.

**W5. Phone** (G8).
- Tests at 390px: the sticky section label, its count, no horizontal scroll.

**D1. Docs.** `CLAUDE.md` (`vmn-exp ui` line: `group=`, `kinds=`), `docs/vmn-exp/ui.md`,
`docs/vmn-exp/ai-fleet-tracking.md` (where fleets show on the board), the plan-20 C2
note, and this plan's row in `docs/plans/README.md`.

## 4. Sequencing

| Wave | Units (parallel worktrees) | Depends on |
|---|---|---|
| 1 | S1 · W1 (against a mocked K1) | — |
| 2 | S2 · W2 · W4 | S1, W1 |
| 3 | W3 · W5 · D1 | W2 |

After each wave: `/simplify`, rebuild the bundle, light/dark screenshots at 1440 and
390. Only targeted Python tests per unit, plus the whole web suite once per merge.

## 5. Out of scope / open questions

- **Nested grouping** (group by parent, then by `params.lr`). W&B has it. One level
  covers sweeps and fleets; revisit after use.
- **Grouping in the CLI** (`vmn-exp list --group`). It can come later on top of
  `leaderboard_groups.py`.
- **Open question: outers that log real metrics.** An orchestrator might log an
  ensemble score, for example. With G1 they are hidden by default but their group
  header shows their own value in a `own` sub-line when the outer has metrics. Is that
  enough, or should such outers stay rows by default?
- **Open question: default aggregate.** Best (goal metrics) is proposed. W&B defaults
  to mean. Best answers "which sweep found the best run". Mean answers "which config is
  robust".
