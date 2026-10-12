# Plan 20: dashboard flows that beat W&B and MLflow

> Plan 19 fixed the shell. The pages behind it still hide what vmn knows that W&B and MLflow
> do not: the exact code of every run, the diff between any two, the way back to either,
> and a status that cannot lie. This plan reorganises the dashboard around the eight jobs
> people open it for, fixes the correctness bugs that undermine every comparison, and
> carries over the open items of the plan-19 re-critique.
>
> Paths are relative to `packages/vmn-exp/webui/src/` unless they start with
> `packages/`, `ui/` (= `packages/vmn-exp/src/vmn_exp/ui/`) or `docs/`.

Status: **proposal** (2026-10-12).

Sources:
- The 2026-10-12 review (three passes). It used screenshots of a `uiload` smoke profile
  (531 runs, live jobs, sweeps, stuck/failed) and a real git repo with stamps and runs
  that change code.
- `.impeccable/critique/2026-10-12T09-48-04Z__packages-vmn-exp-webui-src-app-tsx.md`
  (25/40, after plan 19).
- `PRODUCT.md` (principles: storage is the truth, every number traces to code, solo
  first, scale is normal, same words as the CLI).

Sections: §0 ground truth, §1 the flows and their targets, §2 decisions, §3 contracts,
§4 work units (A correctness, B run page, C leaderboard, M compare, E consistency; decisions are D1–D12, contracts K1–K6), §5 sequencing and worktrees, §6 verification.

## 0. Ground truth (verified against `2307139c`)

| Fact | Where |
|---|---|
| The diff page's metric table uses the **last** value, not the summary policy. A `goal=min` loss shows 0.0056 (last) where the row, run page and `vmn-exp list` show 0.00275 (min) | `ui/readers/diffs.py:76` (`latest_metrics(read_log(...))`), `packages/vmn-exp-sdk/src/vmn_exp/core/log.py:48` |
| Every metric without a schema entry gets a goal: `MIN_LIKE` names → min, **everything else → max**. So `seed`, `batch_size`, `epochs`, `grad_norm_*`, `lr_now`, `sys_rss_mb` all get an `↑` and a green "best" | `util.ts:105-117` |
| Numeric params fold into `row.metrics` by design (sorting and queries rely on it). The run page Metrics card, compare-runs Metrics section and Charts → Trend sparklines all render that fold, so params appear twice and as "metrics" | `MetricsCard` (`pages/RunSections.tsx`), `pages/compareRunsData.ts:62`, Charts panel |
| A param that hid a once-logged metric is tracked (`note_param` → `firsts`). A metric logged more than once has a `metric_summary` entry | `packages/vmn-exp-sdk/src/vmn_exp/core/metric_summary.py:156` |
| Leaderboard sortable `<th>`s have `onClick` but no `tabIndex`, key handler or `aria-sort`; there is no `aria-sort` anywhere in `src/` | `pages/LeaderboardHead.tsx:150-176` |
| The five "Inner runs" columns (`total waiting running done failed`) show when any outer row is loaded; for every single run they are blank. At 1440px they push all metric columns off-screen | `pages/innerRunColumns.ts:7-17` |
| The subtitle "190 of 531 runs" compares top-level table rows with `data.total` (which counts inner runs) even with no filter | `pages/Leaderboard.tsx` (`tableRows!.length !== data.total`) |
| The run page order is Status → Error → Fleet → Sweep → Metadata/Params → Metrics → Training curves → Media → Log + Reproduce → Provenance (Environment) → Lineage → Similar → Comments. **There is no code/patch section and no link to the diff page.** Reproduce lands around 3300px on a failed run | `pages/Run.tsx:157-197`, `pages/Run.tsx:86-116` |
| The run patch payload the CLI prints for `show --patch` exists as a function (`{text, truncated}` or `{text: null, reason}`) but no UI route serves it | `packages/vmn-exp/src/vmn_exp/cli/views.py:109` (`patch_payload`) |
| The failure card says "No exception was recorded — exit code N." It links to `#output` only when `outputs/output.log` exists; it never shows the tail inline | `components/RunErrorCard.tsx:44`, `components/RunOutput.tsx` |
| The selection bar offers three separate destinations: Code diff (`compare?v=&to=`), Compare in table (`compare-runs?sel=`), Overlay curves (`overlay?runs=a,b`) | `pages/LeaderboardSelectionBar.tsx:118-125` |
| `.compare-section th { text-transform: uppercase }` turns run names and verstrs in column headers into `LIVE-000001` / `0.1.0-DEV.654F4AF…`. Verstrs are case-sensitive, hex is lowercase | `styles.css:672` (also `:295`, `:517`, `:550`, `:578`) |
| `LiveToggle` labels its off state "Live off", although the page already polls by itself while a run is running | `components/LiveToggle.tsx:17`, `pages/Leaderboard.tsx` (`usePolling(..., live \|\| anyRunning)`) |
| `Duration` prints a rounded relTime and the exact seconds side by side, which can disagree (`36s 37s`) | `pages/RunSections.tsx:7,38` |
| An outer run lists its children twice: as verstrs in Status (`children`) and again in the Fleet table, whose Progress column is `—` for every child | `pages/RunSections.tsx` (`StatusCard`, `FleetCard`) |
| A `kind: git` workspace whose path is not a repo makes `/tree` raise `InvalidGitRepositoryError` → the page shows "Error: Internal Server Error" | `ui/` tree route, `/tmp/vmnux/run/ui.log` |
| A diff whose snapshots cannot be materialised shows "Error: Failed to materialize snapshots for diff", with no cause, no picker and no CLI line | `pages/Compare.tsx`, `ui/server.py:506` |
| Compare-runs with an unknown ref adds a column of `—` for it and still counts it in "N runs side by side" | `pages/CompareRuns.tsx`, `pages/compareRunsData.ts` |
| The status rollup in the sidebar already links (`?status=stuck`) | `components/shell/StatusRollup.tsx:12` |
| ⌘K CLI hints now go through `vmnExpCommand` (plan-19 P2 "hints omit vmn-exp" looks fixed; re-verify) | `components/palette/paletteItems.ts:47` |
| `Y_AXIS_SIZE = 56` still clips long sparkline y-labels | `util/curveOptions.ts:69` |
| The Models page uses a native unstyled `<select>` ("all kinds"); the Reports page uses an unlabelled `title` input and a raw checkbox | `pages/Models.tsx`, `pages/Reports.tsx` |
| On workspace pages (Models, Reports) the app switcher shows "choose app" and greys out the app nav, even when the user just came from an app | `components/shell/Sidebar.tsx` |
| `tree_status` is `rollup_status` over the run's **whole subtree including itself**, with precedence `failed > stuck > running > created > succeeded`. An outer run that never ran (a grouping record from `vmn-exp create`, or a sweep outer; no `run_state.yml`) is `created`, so its tree is `created` even when every child succeeded. Seen on `ml_app` `lr_layers_grid`: `status: created, tree_status: created, kind: outer`, Fleet card "16 succeeded" | `packages/vmn-exp-sdk/src/vmn_exp/core/tree.py:31-37`, `_subtree_statuses` (`:77`) |
| The run page headline pill is the run's **own** status; "tree X" appears only when `tree_status != status`, so the case above shows a bare `created` above a "16 succeeded" Fleet card | `pages/RunSections.tsx` (`StatusCard`), `pages/LeaderboardRow.tsx:127` |
| Unclaimed sweep trials are not records, so the subtree cannot know a sweep is incomplete. `core/sweep/summary.py:summarize` has `run_cap`, `trials`, `claimed`, `unstarted`; a grid's size follows from its spec | `packages/vmn-exp-sdk/src/vmn_exp/core/sweep/summary.py:125-146`, `core/sweep/spec.py` |
| File sizes to respect (~200-300 lines per file): `Run.tsx` 201, `RunSections.tsx` 271, `Leaderboard.tsx` 283, `LeaderboardRow.tsx` 262, `styles.css` 825 (no new rules there, use per-component CSS) | `wc -l` |

## 1. The flows

Each flow lists the job, what it takes today, the W&B and MLflow equivalents, and the
target. W&B and MLflow behaviour is from product knowledge, not tested side by side. The
target is the bar each work unit in §4 must reach.

| # | Job | Today | W&B | MLflow | Target |
|---|---|---|---|---|---|
| F1 | "Is anything broken?" | Sidebar `40 stuck` link, small grey text | Run state in table | Stored status; dead runs stay RUNNING | An attention strip above the board: stuck · failed (24h) · running, each a filter; hidden when all is well |
| F2 | "Which run is best?" | No metric column visible at 1440px; params crowned "best"; 3 filter inputs + ~12 controls before data | Logged metric columns, header sort | Metric columns, header sort | Goal metrics + varying params visible by default, best-first; one query bar; keyboard-sortable |
| F3 | "Why did this run do better/worse?" | No path from a run to its code. Select 2 on the board → Code diff, which shows wrong (last) values | `diff.patch` file per run, no run-vs-run diff | Commit hash only | A **Changes** card on the run page: vs base / parent / best / previous on branch / fork-or-rerun origin; metric delta + files + diff. 1 click from the run |
| F4 | "Get me back to this exact state" | CLI commands at ~3300px | `wandb restore` CLI | Check out a commit, dirty work lost | **Reproduce ▾** in the run header: `restore` / `rerun` / `export` with copy and one line each. 2 clicks from any number |
| F5 | "Compare these runs" | Three separate pages; uppercased IDs; params as metrics; legend shows verstrs | One workspace, panels follow the selection | Compare page (params/metrics/charts) | One **Compare** page, tabs Curves · Table · Code, one selection, `@N name` everywhere, only-differing on |
| F6 | "Why did it fail?" | "No exception was recorded — exit code 1." | Logs tab (stdout) | Little | Failure card: output tail inline, last step reached, **diff since the last good run** of the same command |
| F7 | "Watch a live run / sweep" | "Live off" button; children listed twice; Progress all `—`; an outer whose 16 children succeeded reads `created` | Sweep page, parallel coords, live charts | Nested runs, no rollup | `● live · updated 3s ago` indicator; fleet/sweep table with `@N name`, status, varied params, goal metric, step progress; parallel coords on the sweep run |
| F8 | "Find it again / show a teammate" | URLs, saved views, ⌘K, Similar runs | Reports, URLs | URLs | Copy link in the run header; Similar runs next to Changes |

Success: on every flow vmn is at least level with both, and ahead on F1, F3, F4 and F6
(code and status are what the others lack). The plan-19 critique target moves from 25/40
to ≥ 32/40 on a re-critique of the whole dashboard, not just the shell.

## 2. Decisions

**D1. A metric has a direction only when someone declared it, or when the name is
unambiguous.** `metricGoal` returns `"min" | "max" | null`. The goal comes from the
schema (conf or run `define_metric`). Failing that, `MIN_LIKE` gives min, and a new
`MAX_LIKE` (`acc|accuracy|f1|auc|precision|recall|map|bleu|rouge|r2|iou|dice|score|reward`
as name parts) gives max. Everything else is `null`. With `null` there is no arrow, no
"best", no best-first sort and no good/bad delta colour. Sorting a goal-less column
starts descending, labelled "high first". The sort-order caption becomes
"high first"/"low first" instead of "best first"/"worst first" for such columns.

**D2. Params are shown as params.** The display layer (not the fold) treats key *k* of
`row.metrics` as a param when `k ∈ params` and *k* has no `metric_summary` entry and no
series (it was never logged as a metric more than once). Such keys appear under Params
only: in the run Metrics card, compare Table's Metrics section, the Trend sparklines,
the diff page deltas, Charts axes, and the leaderboard's metric column group (they move
to the param group). Queries and `metrics.<k>` sorting keep working unchanged.

**D3. Identifiers are never transformed.** No `text-transform` on any element that can
contain a run name, verstr, app, branch, model or metric name. Section labels may stay
uppercase.

**D4. Every metric value shown for a run uses the row's summary policy**
(`row.metrics[k]`), everywhere: leaderboard, run page, compare, diff, overlay tooltips'
headline value, reports. `last` is shown only where it is labelled `last`.

**D5. The run page answers questions in order.** First "what is it", then "how did it
go", "what changed", "how do I get back", and finally the details:

1. Header: name, `@N`, status pill, branch, base version; actions **Reproduce ▾**,
   **Copy link**, Add to report, live indicator.
2. Note and tags.
3. Failure card (failed/stuck only).
4. Training curves (goal metrics first).
5. **Changes** (new).
6. Fleet/Sweep (outer runs only).
7. Params (varied first) | Metrics (no params, D2).
8. Similar runs | Lineage.
9. Collapsed by default: Status details (pid, host, heartbeat, command, exit code),
   Log, Environment, Media (open when present), Comments (open when there are any).

**D6. One Compare page.** `compare-runs` becomes the Compare page with tabs `curves`
(default), `table` and `code`, in `?tab=`, sharing `?sel=` (repeated). The `code` tab
diffs two runs. With more than two selected, it diffs the first against a picker that
defaults to the second. The old `overlay?runs=` and `compare?v=&to=` URLs redirect to
it (`tab=curves` / `tab=code`), so links and reports keep working. The selection bar
gets one primary action, **Compare (N)**, plus Archive.

**D7. "Changes" baselines.** Shown in order, and only when they exist:

- `base` (the run's own patch against its stamped base version: what the working tree
  added). This is the default when the run captured a dirty tree or local commits.
- `parent` (outer run).
- `forked_from` / `rerun_of`.
- `previous` (the latest earlier run on the same branch with the same command).
- `best` (the app's best run on the primary goal metric, only when one is declared).

For a clean-tree run the default is `previous`. The run-vs-run baselines reuse
`experiments-diff`. `base` reuses `patch_payload`.

**D8. Reproduce stays copy-first.** No button in the UI restores or reruns. That keeps
the current "no Rerun button" decision and the read-only deployments. The menu shows
the exact commands with copy, each with one line: restore = into this checkout (saves
dirty work first), rerun = throwaway worktree, export = a bundle for a container. In a
writable git workspace, `vmn goto -v <verstr>` is also offered through the existing
Actions job runner, behind a confirm dialog that shows the command.

**D9. Live is automatic, pausing is the choice.** While any visible run is running, the
page polls (as today) and shows `● live · updated Ns ago`. A `Pause` control stops it,
and Resume restarts it. With nothing running, the indicator is hidden and a "Refresh"
button shows instead. `LiveToggle` goes away.

**D10. The leaderboard has one filter grammar.** The query bar is the filter.
- Status chips, branch and archived are shortcuts that write clauses into it, shown as
  removable tokens. Typing the clause by hand gives the same token.
- Free-text search becomes a `~` clause on name/note/verstr.
- `similar` becomes a mode of the search box (a toggle inside it), not a chip among
  status filters.
- A `?` next to the bar opens query help: fields, operators, examples drawn from this
  app's metric and param names.
- The URL keeps today's params (`q`, `status`, `branch`, `archived`), so saved views
  and links keep working.

**D11. Default leaderboard columns:**
- `#`, status, experiment (name, verstr, branch on one line).
- The declared-goal metrics (sort default = first declared goal, else `#`).
- Up to 6 params whose values vary across the loaded rows.
- `when`.

The rest comes from the column picker; user prefs (`useColumnPrefs`) still win. Inner
runs collapse into one `inner` cell (`5 · 4 running · 1 failed`), shown only when an
outer row is loaded.

**D12. An outer run's headline is its tree.** An outer run that never ran (no run
state: own status `created`) is a container, and its own `created` is left out of its
`tree_status` rollup. An outer that did run (a `vmn-exp run` orchestrator, an SDK parent)
still counts, so a failed orchestrator still fails its tree. A sweep outer whose trials
are all finished but number fewer than the sweep's planned size (grid size, else
`run_cap`; unknown for an uncapped random/bayes sweep) rolls up to `created`, and the
UI says `16/20 · incomplete`. On the run page and in the leaderboard row, outer runs
show the tree status as the main pill, with the inner count (`succeeded · 16/16 inner`).
Their own status shows as a secondary line only when it is `failed` or `stuck`, or
differs from the tree while running. The `tree_status` description in `CLAUDE.md`
changes with it.

## 3. Contracts

**K1. `experiments-diff` metrics.** `metrics_delta` is computed from the two rows'
`metrics` (summary policy, D4) and carries the goal per key:
`{key, from, to, delta, goal: "min"|"max"|null, param: bool}`. Run-declared goals
resolve the same way as `metric_schema`. Keys the display treats as params (D2) carry
`param: true`, so the client can show them in a separate "params changed" block.

**K2. `GET .../experiments/{verstr}/patch?max_bytes=`.** This returns
`patch_payload(metadata, patches, max_bytes)` unchanged: `{text, truncated}` or
`{text: null, reason}`. It also adds `files: [{path, added, removed}]` parsed from the
text. Read-only, lock-free, ETag on the code object's identity. Viewer role.

**K3. `GET .../experiments/{verstr}/baselines`.**
- Shape: `{base?, parent?, forked_from?, rerun_of?, previous?, best?}`, each
  `{verstr, idx, name, status}`.
- `previous`: the latest earlier row with the same `branch` and `command`.
- `best`: from `LeaderboardCache.ordered` on the primary declared goal.
- `base`: the run itself when it has a patch, and is otherwise absent.
- All from the lock-free index snapshot; no git.

**K4. Failure context in run detail.** The detail payload gains:
- `output_tail: {lines: [...], truncated: bool} | null`: the last 40 lines of
  `outputs/output.log`, read with a range read, capped at 16 KB.
- `last_step: {step, of}`: `of` = `params.epochs` or `params.max_steps` when numeric,
  else null.
- `last_good`: the latest succeeded row with the same `command`, as `{verstr, idx, name}`.

All three are present only for `failed`/`stuck`.

**K5. Tree on a non-repo git workspace.** `/tree` and `/actions`-backing endpoints
return 409 `{"detail": ..., "reason": "not_a_repo", "path": ...}` instead of a 500. The
UI renders it with `NotFound`-style copy (cause + `git -C <path> status` hint).

**K6. Diff failures carry a reason.** Materialisation failures return 422
`{reason: "code_missing"|"no_code"|"restore_failed", detail, verstr}`. The Code tab
shows the reason, keeps both pickers usable and prints the CLI line.

## 4. Work units

Each unit is test-first. A vitest or pytest test is written red, then the minimum code
makes it green. A unit lists its tests before its code. *(prev)* marks items carried
over from the plan-19 critique.

### Phase A — correctness (do first; every comparison depends on it)

**A1. Diff metrics use the summary policy** (K1). `ui/readers/diffs.py`.
- Tests (`packages/vmn-exp/tests/`): a run that logs `loss` [1.0, 0.002, 0.005] with
  `define_metric("loss", goal="min")` gives `from == 0.002`. A param-only key carries
  `param: true`. A conf glob goal is honoured.
- Web: `pages/Compare.tsx` colours a delta by `goal`, not by sign, and shows nothing for
  `goal: null`. Test: `lr +0.04` with `goal: null` is neutral.

**A2. Goal resolution** (D1). `util.ts` `metricGoal` → nullable, add `MAX_LIKE`.
- Tests: `seed`, `batch_size`, `grad_norm_l000`, `lr_now` → null; `val_acc`, `f1` →
  max; `val_loss`, `rmse` → min; a schema goal beats both.
- Call sites follow: `LeaderboardHead.headInfo` (arrow only with goal), the leaderboard
  `bestOrder`/caption, `compareRunsData.bestOf`, Trend/Bar/Scatter "best", MetricsCard
  arrows, ParamPlots, SweepSection. One test per call site asserting no arrow/"best" for
  a goal-less key. *(prev P1 "best on every sparkline")*

**A3. Params are params** (D2). A new `util/paramKeys.ts:isParamOnly(key, row|detail)`.
- Tests: the fold key equal to a param with no summary/series → param. The same key
  logged as a metric more than once → metric.
- Apply to MetricsCard, compare Table, Trend sparklines and leaderboard column groups.
  One test each.

**A4. Identifiers keep their case** (D3). Remove `text-transform` from `.compare-section
th` and any header holding IDs. Section labels move to a `.label-caps` class.
- Test: rendered compare header text equals the verstr exactly (`textContent` and
  computed style).

**A5. Small truths.**
- `Duration` shows one value: relTime with the exact seconds in `title`. Test:
  36.6 s renders "37s" once.
- Heartbeat is hidden for finished runs (shown in Status details).
- Duration/runtime of 0 s show `<1s`. *(prev "duration/runtime both 0s")*
- "190 of 531 runs" becomes `190 runs · 531 incl. inner` without a filter and
  `N of 190 runs` with one. Test both.

**A6. Error states** (K5, K6).
- Server tests: a non-repo git workspace → 409 `not_a_repo`; a missing code object →
  422 `code_missing`.
- Web tests: tree page renders cause + hint, not "Internal Server Error". The Code tab
  keeps its pickers on 422.
- Compare with an unknown ref: a "not found: nope (remove)" chip, no `—` column, and
  the count excludes it.

**A7. Outer runs report their tree** (D12).
- Core tests (`packages/vmn-exp/tests/`, pure `core/tree.py`):
  - an outer with no run state and 16 succeeded children → `tree_status == "succeeded"`;
  - the same with one failed child → `failed`, and with one running child → `running`;
  - an outer that ran and failed with succeeded children → `failed`;
  - an outer that ran and is still running → `running`;
  - nested: an inner outer without run state under an outer without run state;
  - the cyclic-graph path (`_has_cycle`) gives the same answers as the linear one.
- Sweep tests: a grid sweep of 20 points with 16 finished trials → `created`
  (incomplete). With 20 → `succeeded`. An uncapped random sweep follows its trials. The
  planned size comes from `core/sweep/spec.py`, so `core/tree.py` stays pure: the
  sweep's planned size is passed in, or attached to the row by the index, never read
  from storage in `tree.py`.
- Index: bump the index `SCHEMA_VERSION` if `tree_status` is cached in the index rows.
  Queries on `tree_status` and `vmn-exp list` follow automatically; add one CLI test
  (`vmn-exp list` shows the outer as succeeded).
- Web tests: `StatusCard` and `LeaderboardRow` lead with the tree pill for `kind ==
  "outer"` plus `16/16 inner`, show the own status only per D12, and show
  `16/20 · incomplete` for the sweep case. Single and inner runs are unchanged.
- Docs: the `CLAUDE.md` nesting bullet (`tree_status` rule) and
  `docs/vmn-exp/experiments.md` (nesting/status section).

### Phase B — the run page (F3, F4, F6, F7, F8)

**B1. Patch + baselines endpoints** (K2, K3). New `ui/routes_run_code.py`
(`register(app, prefix, …)` pattern; `server.py` is at its size limit).
- Tests: a dirty-tree run returns text + files. A clean run returns
  `reason: no_code`/absent `base`. `previous` picks the same branch + command. `best`
  is absent without a declared goal. The ETag repeats.

**B2. Changes card** (D7). `components/RunChanges.tsx` (+ `RunChanges.css`). It holds
a baseline picker, a metric delta (top 5 goal metrics by |Δ|, then "+N more"), a files
list (`path +a −r`) and an expandable unified diff (reuse the diff renderer from
`pages/Compare.tsx`, moved to `components/DiffText.tsx`). Its footer is "Open in Compare
→" (`compare-runs?tab=code&sel=a&sel=b`).
- Tests: default baseline per D7; switching baseline refetches; no code → a one-line
  reason; read-only workspaces render it.

**B3. Header actions** (D8, F8). `components/RunHeaderActions.tsx`:
- Reproduce ▾ (menu, keyboard reachable, Esc closes, focus returns), with copy buttons
  that announce "copied" via a live region.
- Copy link (the canonical `/ws/…/run/<verstr>` URL).
- Optional `vmn goto` through the job runner with a confirm dialog (writable git
  workspace only).
- Tests: menu a11y, the copied text equals the CLI command
  (`vmnExpCommand`/`vmnCommand`), goto hidden when read-only.
- The old Reproduce card is removed.

**B4. Failure card** (K4, F6). Extend `RunErrorCard` with `output_tail` (mono, last 40
lines, "open full output" → `#output`), "stopped at step 38 of 86" and "Since it last
worked: @41 hist-000488 → Changes" (sets the Changes baseline to `last_good`).
- Server tests for K4 (range read cap, absent for succeeded).
- Web tests for each part's presence/absence.

**B5. Page order and disclosure** (D5). `pages/Run.tsx` becomes a composition of
sections. Status details, Log, Environment and Comments sit in `<details>`-style
disclosures that remember their state per user (localStorage), with headings kept for
screen readers.
- Tests: the order of section headings; Log is collapsed by default and still holds
  the last 10 entries in its summary row.
- Keep `Run.tsx` < 200 lines by moving sections into `pages/RunLayout.tsx`.

**B6. Fleet / sweep table** (F7). `FleetCard`:
- Drop the `children` row from Status.
- Rows show `@N name`, status, the params that vary among children, the goal metric
  (best marked per D1) and progress = `last_step/of` when known, else hidden (no `—`
  column).
- Sortable, keyboard-accessible (same header component as C3 below).
- A sweep run also gets the parallel-coordinates chart over its trials.
- Tests: no duplicate verstrs on the page, the Progress column is hidden when unknown,
  sorting by the goal metric.

**B7. Live indicator** (D9). Replace `LiveToggle` on Run and Leaderboard with
`components/LiveStatus.tsx`.
- Tests: running → "live · updated Ns ago" + Pause; Pause stops polling; with nothing
  running → Refresh only; `aria-live="polite"` announces only state changes, not ticks.

### Phase C — the leaderboard (F1, F2)

**C1. Default columns** (D11). `hooks/useLeaderboardColumns.ts` + `pages/leaderboardColumns.ts`.
- Tests: with no prefs, goal metrics come first and pinned after the experiment
  column; at most 6 varying params; constant params are hidden; prefs override; the
  primary metric is visible at 1280px.

**C2. Compact inner cell** (D11). `innerRunColumns.ts` collapses to one `inner` column
(`5 · 4 running · 1 failed`, colour-coded with text). The header group goes away.
- Tests: absent without outer rows; the counts' text; screen readers read "5 inner
  runs, 4 running, 1 failed".

**C3. Keyboard and screen-reader sorting.** `LeaderboardHead`: a `<button>` inside each
sortable `th`, `aria-sort` on the `th`, visible focus ring. Drag/resize stay
mouse-only, and a column menu (sort, hide, pin, move left/right) adds the keyboard
equivalents.
- Tests: Enter/Space sorts, `aria-sort` follows, the menu moves a column.

**C4. One filter grammar** (D10). `components/LeaderboardFilter.tsx` (191 lines) is
split into `QueryBar` (tokens + text), `FilterShortcuts` (status/branch/archived as
token writers) and `SimilarToggle` (inside the search box).
- Tests: clicking `failed` adds a `status = "failed"` token and sets `?status=`
  (URL compatible); removing the token clears it; a hand-typed clause becomes the same
  token; similar mode keeps the other tokens.
- *(prev P1 "header overload", "status chips vs similar toggle look alike")*

**C5. Query help.** A `?` popover next to the bar listing fields (`metrics.<this app's
keys>`, `params.<…>`, `status`, `branch`, `tags.<…>`), operators and three examples
built from the app's facets.
- Tests: examples use real keys from facets; Esc closes; focus returns.
- *(prev "Help and Documentation 1/4")*

**C6. Attention strip** (F1). `components/AttentionStrip.tsx` above the board, from
`experiments-status` (no new endpoint): `⚠ 40 stuck · 3 failed in 24h · 12 running`,
each part a filter link.
- Tests: hidden when there are 0 stuck and 0 recent failures; links set the right
  token; `role="status"`.
- Its counts must equal the board's (fixes *(prev)* "apps 54 runs vs leaderboard 32 of
  53" if it is still present; add a test across `/apps` and `experiments-status`).

**C7. Toolbar distill.** Keep `New run` (primary when writable), `Views` and `Columns`
on the right; the live indicator and the "best in column" legend go into the table
caption. Target: ≤ 7 controls before the first row.
- Test: count focusable controls between the h1 and the table ≤ 7 (default view).

**C8. Mobile board** (< 640px). Rows become cards: name + status line, the primary
metric large, branch · when.
- Tests at 390px: no horizontal scroll at page level; `Views` is not clipped; the
  primary metric is visible.
- *(prev P2 mobile chrome: wrapping run header, ⌘K hint on touch, palette CLI column
  truncation, unexplained identity initial — fix in the same unit)*

### Phase M — Compare (F5)

**M1. Unified Compare page** (D6). `pages/Compare/` folder: `ComparePage.tsx` (tabs,
selection chips with remove/add), `CurvesTab.tsx` (today's Overlay), `TableTab.tsx`
(today's CompareRunsTable), `CodeTab.tsx` (today's Compare diff, using
`components/DiffText.tsx` from B2). `routes.tsx` maps `overlay` and `compare` to
redirects.
- Tests: tabs keep `sel`; the redirect from `overlay?runs=a,b` → `?tab=curves&sel=a&sel=b`
  and from `compare?v=a&to=b` → `?tab=code&sel=a&sel=b`; reports' `vmn-panel` links still
  resolve; the crumb reads `compare N runs`.

**M2. Compare content fixes.**
- The legend and column headers use `@N name` (verstr in `title` and a copy button).
- "Only differing" is on by default.
- The Table tab gets Metrics (D2, no params) and Params sections with a "params
  changed" count.
- Best follows D1.
- The Curves tab: `x: declared` becomes "x axis: step / wall / relative / <metric>" as
  one labelled segmented control; `Log y` gets `aria-pressed` and a visible on state;
  smoothing shows its value.
- Tests per item.

**M3. Selection bar.** One primary `Compare (N)` (disabled with the reason below 2) +
Archive/Unarchive. Test: it opens `compare-runs?tab=curves&sel=…`.

### Phase E — consistency and carried-over items

**E1. Workspace pages' controls.**
- Models' kind filter becomes the shared segmented control.
- Reports' create form becomes a labelled `New report` dialog (title field with a
  visible label).
- "show archived" uses the shared toggle.
- Drop the redundant subtitle *(prev)*; give Models descriptions in place of "—" *(prev)*.
- Tests: labels are associated; no native unstyled select remains (lint-style test over
  `pages/`).

**E2. App context on workspace pages.** The sidebar keeps the last app (per workspace,
from the URL history) as the switcher's value, with the app nav enabled and pointing to
it.
- Tests: Models after `/app/demo` shows `demo`; a fresh visit shows "choose app".

**E3. Metric summaries wrap cleanly.** In the Metrics card, the name and goal arrow
never split; `last · min · max · first · mean` wrap as whole pairs. Test with
`grad_norm_l000` at 420px card width.

**E4. Layout.** Metadata | Params cards no longer stretch to equal height
(`align-items: start`); Metrics takes the full width when Params is short. Test: the
computed style on the grid.

**E5. Trend charts.** One series colour (the accent) per sparkline, with "best" in the
good colour only per D1; x-axis tick labels on; `Y_AXIS_SIZE` sized from the widest
label *(prev "y-labels clipped")*. Tests: the uPlot options' stroke is constant across
cards; the axis size grows for `1.792e+9`.

**E6. Remaining plan-19 critique items.** Re-verify each against `master`, fix those
still open, and record "already fixed" in the PR:
- Crumb repeats the app when ws = app; the store path `.vmn/store` in primary chrome
  moves to a provenance popover.
- Recent (⌘K) records failed/dead destinations; an unknown app shows the switcher and
  nav active; the `/tokens` crumb says "not found".
- The first Esc in a filled ⌘K only clears (keep, but show "Esc again to close").
- The sidebar `h2`s precede the page `h1` (make them non-heading labels with
  `aria-label` on the nav groups).
- The copy-as-CLI icon is faint (raise to `--text-2`, 3:1 minimum).
- `RunLog.tsx:83` 10px badge → 11px+; placeholder `#757575` → AA on both themes;
  `created` pill 4.49:1 → ≥ 4.5:1.
- Apps rollup single amber dot (add the count text); visible rollup "1 stuck" vs an
  aria-label listing all counts (make them match).
- Recent icon inconsistency; dark sidebar vs content separation (a 1px border token).
- `.select-wrap ▾` glyph in Actions/RunPicker (use the shared chevron icon).
- Store workspaces: `/tree` issues one 400 before `needs-git` (gate the query on
  workspace kind).

**E7. Actions page.** `Goto` is the riskier action, so it gets the confirm dialog (it
shows the command and "other apps untouched") and the same weight as `Preview`. Test:
goto requires the confirmation.

## 5. Sequencing and worktrees

Phase A goes first and in parallel (A1 server+web, A2+A3 web utils, A4–A6 small). Every
later unit renders goals, params or IDs, so building on unfixed behaviour would mean
rewriting tests. Then:

| Wave | Worktrees (parallel, each owns its red-green-refactor) | Depends on |
|---|---|---|
| 1 | `a1-diff-summary` · `a2-a3-goals-params` · `a4-a5-truths` · `a6-error-states` · `a7-outer-tree-status` | — |
| 2 | `b1-run-code-api` · `c1-c2-columns` · `c3-sort-a11y` · `e1-e2-ws-pages` · `e3-e5-run-cards` | wave 1 |
| 3 | `b2-changes-card` · `b3-header-actions` · `b4-failure-card` · `c4-c5-filter-grammar` · `d1-compare-page` | B1 (B2, B4), wave 1 |
| 4 | `b5-run-layout` · `b6-fleet-sweep` · `b7-live-status` · `c6-c7-attention-toolbar` · `d2-d3-compare-content` | B2–B4, M1, C4 |
| 5 | `c8-mobile` · `e6-critique-carryover` · `e7-actions` | everything above |

Rules (from `CLAUDE.md`):
- Every unit is test-first.
- Sub-agents run targeted tests only (`npm test -- <file>` in `packages/vmn-exp/webui`,
  `--specific_test` for pytest).
- Files stay ≤ ~300 lines, and units that would exceed that split.
- No new rules in `styles.css` (per-component CSS files).
- Worktrees are removed and their branches deleted when merged.
- After each wave: `/simplify`, then rebuild the bundle (`npm run build`).
- `CLAUDE.md` gets updated where the UI contract changes (the run page sections, the
  Compare routes, `/patch`, `/baselines`, the K4 fields).

## 6. Verification

1. **Tests.** The full web suite (`npm test`) plus the exp suite
   (`./packages/vmn-exp/tests/run_pytest.sh`) once on `master` after each wave.
2. **Screenshots.** A `uiload` smoke run plus the small real git repo (two stamps,
   three runs changing code) serve the dashboard. Headless Chrome captures the
   leaderboard, the charts tab, run (succeeded / failed / outer / sweep), Compare (all
   three tabs), the stamp tree, Models, Reports, Actions and the 390px board and run
   at 1440 and 390 px. Use `--run-all-compositor-stages-before-draw`, or `LazyMount`
   charts render blank.
3. **Flow acceptance**, each scripted as a vitest flow test, plus a manual check:
   - F2: the primary metric is visible without horizontal scroll at 1280px.
   - F3: from a run, ≤ 1 click to its diff against the default baseline.
   - F4: ≤ 2 clicks from a metric value to a copied `restore` command.
   - F5: switching curves ↔ table ↔ code keeps the selection, 1 click each.
   - F6: a failed run shows the output tail without scrolling at 1440×900.
   - F1: the stuck count on the strip equals the rows behind its link.
   - F7: an outer run whose children all succeeded never reads `created`; an
     incomplete sweep reads `N/M · incomplete`.
   - Every page has no uppercased identifiers and no goal arrow on a goal-less metric.
   - Keyboard only: sort, filter, select, compare and copy a command.
4. **Re-critique** the whole dashboard (not only `App.tsx`) and store it under
   `.impeccable/critique/`. Target ≥ 32/40, with no P0/P1 open.
5. **Docs.** `docs/vmn-exp/ui.md` (run page sections, Compare tabs, the new endpoints),
   `docs/vmn-exp/vmn-vs-mlflow.md` (the Changes card and the failure "since last good"
   under "Where vmn is genuinely ahead"), and the plans index row.
