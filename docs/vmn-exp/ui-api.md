# vmn-exp ui: HTTP API

The REST API that `vmn-exp ui` serves; the dashboard, its flags and its
deployment are in [ui.md](ui.md).

- [Outer runs, scope and search](#outer-runs-scope-and-search)
- [Experiment status fields](#experiment-status-fields)
- [Server meta and roles](#server-meta-and-roles)
- [Git context](#git-context)
- [Status counts and rollup](#status-counts-and-rollup)
- [Filtering with a query](#filtering-with-a-query)
- [Paging, sorting and order](#paging-sorting-and-order)
- [Grouped runs](#grouped-runs)
- [Columns for whole-set charts](#columns-for-whole-set-charts)
- [Parameter importance](#parameter-importance)
- [Pivot heatmap](#pivot-heatmap)
- [Baseline compare](#baseline-compare)
- [Facets](#facets)
- [Run detail is bounded](#run-detail-is-bounded)
- [Run code: patch and baselines](#run-code-patch-and-baselines)
- [Series for many runs](#series-for-many-runs)
- [Zoom and many keys](#zoom-and-many-keys)
- [Custom x axis](#custom-x-axis)
- [Diffs and artifacts](#diffs-and-artifacts)
- [Media](#media)
- [Lineage](#lineage)
- [Similar runs](#similar-runs)
- [Model registry API](#model-registry-api)
- [Caching and compression](#caching-and-compression)

## API

OpenAPI docs are served at `/api/docs` (`/api/openapi.json`). All paths are
under `/api/v1`; `{app}` is the app's tag form (`root_app-service1` for
`root_app/service1`), `{ws}` the workspace name.

| Method | Path | Answers |
|---|---|---|
| `GET` | `/meta` | [Server meta](#server-meta-and-roles): versions, `read_only`, `mode`, `auth`, `principal`, `role` |
| `GET` / `POST` | `/workspaces` | List (each item with the caller's `role`, [roles](#server-meta-and-roles)) / add a workspace ([Workspaces](ui.md#workspaces)) |
| `DELETE` | `/workspaces/{ws}` | Remove a workspace (204) |
| `GET` | `/workspaces/{ws}/git` | [Branch, HEAD, dirty, store](#git-context) of a git workspace |
| `GET` | `/workspaces/{ws}/apps` | Apps with experiments or versions |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments` | Run rows ([paging](#paging-sorting-and-order), [query](#filtering-with-a-query)); with `group=`, [groups of runs](#grouped-runs) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments?children_of=<v>` | [A run's direct children](#outer-runs-scope-and-search) for the tree, each with its `job` and `open` |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}` | [Run detail](#run-detail-is-bounded) (`latest`, `@N`, prefixes resolve) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}/log?offset=&limit=` | A page of the log, `{"entries", "total"}`, oldest first |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}/artifacts/{path}` | [Artifact download](#diffs-and-artifacts) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}/outputs/{path}` | [One of vmn's own outputs](#diffs-and-artifacts) (`output.log`, media, tables) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}/table/{path}` | A page of a logged [table](#media) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}/histograms/{name}` | One histogram key's [steps](#media) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}/lineage` | [Run lineage](#lineage) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}/patch?max_bytes=` | [The run's patch and changed files](#run-code-patch-and-baselines) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}/baselines` | [Runs to diff it against](#run-code-patch-and-baselines) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}/sweep` | The sweep's spec, summary and trials ([sweeps.md](sweeps.md#status)) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}/summary?split=` | [An outer run's rollup](#outer-runs-scope-and-search) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}/failures?limit=` | [An outer run's failure clusters](#outer-runs-scope-and-search) |
| `GET` | `/workspaces/{ws}/apps/{app}/search?text=&limit=` | [⌘K run search](#outer-runs-scope-and-search) over the app's runs |
| `GET` | `/workspaces/{ws}/apps/{app}/events?scope=` | [Change stream](#outer-runs-scope-and-search) (Server-Sent Events) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}/similar?top=&all_apps=&archived=&q=` | [Runs most like this one](#similar-runs) |
| `GET` | `/workspaces/{ws}/apps/{app}/similar?text=&top=&all_apps=&archived=&q=` | [Runs matching a text](#similar-runs) |
| `GET` | `/similar?text=&top=&archived=&q=` | [Runs matching a text](#similar-runs) over every workspace the caller may view |
| `GET` | `/search?q=&limit=&archived=` | The [query language](#filtering-with-a-query) over every app of every workspace the caller may view ([server.md](server.md#postgres-and-replicas)) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments-columns` | [Whole-set chart columns](#columns-for-whole-set-charts) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments-importance` | [Parameter importance](#parameter-importance) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments-facets` | [Filter vocabulary](#facets) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments-pivot?rows=&cols=` | [Pivot heatmap](#pivot-heatmap) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}/baseline?to=&match=&by=` | [An outer run against its baseline](#baseline-compare) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments-baselines?v=` | [Many outer runs' baseline chips](#baseline-compare) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments-status` | [Status counts and rollup](#status-counts-and-rollup) |
| `GET` | `/workspaces/{ws}/apps-status` | [Every app's status counts](#status-counts-and-rollup), one request |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments-diff?v=&to=` | [Code diff of two runs](#diffs-and-artifacts) |
| `POST` | `/workspaces/{ws}/apps/{app}/series` | [Series of many runs](#series-for-many-runs) |
| `GET` | `/workspaces/{ws}/apps/{app}/experiments/{verstr}/metric-keys?prefix=&offset=&limit=` | [A run's metric names, paged](#zoom-and-many-keys) |
| `GET` | `/workspaces/{ws}/apps/{app}/metrics-schema` | The [effective metrics schema](#paging-sorting-and-order) |
| `GET` / `PUT` | `/workspaces/{ws}/apps/{app}/settings` | The app's [store settings](server.md#app-settings) (`PUT {"text"}`: editor) |
| `POST` | `/workspaces/{ws}/apps/{app}/actions/{action}` | Start a [job](ui.md#actions) |
| `GET` | `/jobs/{id}` | A job's status and log |
| `GET` | `/workspaces/{ws}/apps/{app}/versions` | Stamped versions (git workspaces) |
| `GET` | `/workspaces/{ws}/apps/{app}/tree` | Version DAG (git) |
| `GET` | `/workspaces/{ws}/apps/{app}/tree/root` | Root app's service topology per root version (git) |
| `GET` | `/workspaces/{ws}/apps/{app}/deps?v=&to=` | Dependency pins of `v` (default latest), or their drift to `to` (git) |
| `GET` | `/workspaces/{ws}/apps/{app}/changelog?v=&from=` | Conventional commits grouped between `from` (default: `v`'s previous version) and `v` (default latest) (git) |
| `GET` | `/workspaces/{ws}/apps/{app}/config?v=` | `{"conf", "text"}` of the app's `conf.yml`, from the working tree or as of version `v` (git) |
| `GET` | `/workspaces/{ws}/apps/{app}/reports?verstr=` | [Reports](reports.md#report-api) whose panels show this app (or run) |
| `GET` / `POST` | `/workspaces/{ws}/reports` | List / create [reports](reports.md#report-api) |
| `GET` / `PATCH` / `DELETE` | `/workspaces/{ws}/reports/{rid}` | A report's header and latest revision / its title, archived, pinned / delete it |
| `POST` | `/workspaces/{ws}/reports/{rid}/revisions` | Save a [revision](reports.md#revisions-and-conflicts) (409 on conflict) |
| `GET` | `/workspaces/{ws}/reports/{rid}/revisions/{n}` | One revision |
| `GET` | `/workspaces/{ws}/reports/{rid}/revisions/{n}/data/{panel}` | A [published](reports.md#live-vs-published) panel's data |
| `POST` | `/workspaces/{ws}/reports/{rid}/publish` | Publish a revision with its panels' data |
| `GET` / `POST` | `/workspaces/{ws}/comments` | List / add [comments](reports.md#comments) on a target |
| `PATCH` / `DELETE` | `/workspaces/{ws}/comments/{target}/{id}` | Edit or resolve / delete a comment |
| `GET` | `/workspaces/{ws}/cache/status` | The [cache's state](server.md#self-healing-and-resync) (admin) |
| `POST` | `/workspaces/{ws}/cache/resync?full=` | [Resync the cache](server.md#self-healing-and-resync) (admin) |
| `GET` / `POST` | `/tokens` | List / create [API tokens](server.md#authentication) (admin) |
| `DELETE` | `/tokens/{id}` | Revoke a token (admin) |
| `DELETE` | `/tokens?owner=` | Revoke every token of an owner and close their sessions (admin) |
| `GET` | `/audit?offset=&limit=` | A page of the [audit log](server.md#roles) (admin) |
| `GET` | `/audit/export` | The audit log as JSONL (admin) |
| `GET` | `/diag` | A [diagnostic dump](ui.md#diagnostic-dumps) (admin) |
| | `/workspaces/{ws}/models/...` | [Model registry](#model-registry-api) |

Two groups of routes are served outside `/api/v1`, at these full paths:

| Method | Path | Answers |
|---|---|---|
| `GET` | `/metrics` | [Prometheus gauges](server.md#prometheus-metrics) (viewer) |
| `GET` | `/auth/login` | Start the [OIDC](server.md#authentication) browser sign-in |
| `GET` | `/auth/callback` | The OIDC redirect URI; sets the session cookie |
| `POST` | `/auth/logout` | Close the browser session |
| `POST` | `/auth/device/start` | Start the device flow of `vmn-exp login` |
| `POST` | `/auth/device/token` | Poll the device flow for a login token |

Unknown `/api/...` paths are a JSON 404. A query parameter the route does not
take is a 400 naming it (`Unknown query parameter 'limt'; did you mean 'limit'?`),
never silently ignored; the web page's own URLs are not affected.

`.../experiments` answers one of three shapes, picked by its parameters; a
combination the table refuses is a 400 naming the parameters that conflict:

| Mode | Selected by | Its own parameters | Refused |
|---|---|---|---|
| Flat page | neither of the two below | `last`, `cursor`, `match_subtree` | |
| [Groups](#grouped-runs) | `group=` | `agg`, `rows_per_group`, `group_key`, `collapse_all` (with `top`) | `last`, `cursor` |
| [Tree page](#outer-runs-scope-and-search) | `children_of=` | `last`, `cursor`, `match_subtree` | `group`, a `q` reading `comments` |
| Jobs view (with any of the three) | `top=1\|jobs\|singles` | `top_q`, `job_agg`, `job_agg_by`, `job_agg_value`, `job_agg_metric`, `job_agg_nested` | each of these without `top` |

`offset`, `limit` (groups, for a grouped page), `sort`, `order`, `status`, `q`,
`scope` and `archived` page, filter and order every mode.

Routes that resolve a run ref (run detail, its log page, `experiments-diff`)
answer a ref they cannot resolve with `{"detail": "<message>", "code": "<code>"}`:
`run_not_found` (no such verstr or prefix, `@N` out of range, no runs) is a
404, `ambiguous_ref` (a prefix matching several runs) a 409, `invalid_ref`
(a malformed ref such as `@x`) a 400. Clients branch on `code`, never on the
message.

### Outer runs, scope and search

- **Rows** carry `root` (the top-level ancestor's verstr, null at the top) and
  `failure_sig`. Both are query fields, as is `under("<verstr>")` (in that
  run's subtree). A run that logged notes also carries `note_sig` (its latest
  [note signature](sdk.md#note-signatures)) and `note_minutes` (the epoch
  minute each of its signatures was last noted in); a failed or stuck run
  without an `error_summary` has `failure_sig` `failed | exit=143 |
  note=<its note_sig>`, so its failures cluster by what it noted last
  ("Last note: ..."). `notes ~ "sigterm"` matches the signatures.
- **`experiments?top=1|jobs|singles`** lists top-level runs only (all, those
  with children, those without). An outer run's row carries `job`: `{total, counts,
  done, expected, progress, failed_pct, throughput_per_min, eta_sec,
  declared_progress, metric, goal, best, best_verstr, best_idx, spread,
  rolled}` (`goal` the main metric's, `best` null without one). It takes
  the `job:*` sorts; `job:value` sorts by `rolled.value`, best-first by
  its goal, rows without one last.
  - `rolled` is the row's [aggregate](ui.md#outer-runs-and-the-outer-runs-page):
    `{agg, by, source, metric, goal, percentile, value, n, of, conflicts,
    verstr, approx}`. `source` is the `job_agg_value`; `percentile` names a
    tail's (`p90`, else null); `n` of `of` units have a value (`of` counts
    distinct field values for `field:`, all runs for `runs`); `conflicts`
    are the field values two units share (left out); `verstr` is the unit
    holding the value (a quantile's lower neighbour; null for the mean, and
    for `runs` but its `best`); `approx` is true for a `runs` quantile (the
    merged sketch, ~1%). `value` is null without a goal or a unit with one.
    `mixed`/`policies` (`{policy: runs}`) name the job's runs overriding the
    schema's summary policy of the metric (plan 32 F1), absent without one.
  - For `field:`/`kind:` units `rolled` also carries `nested` (whether
    carriers at any depth count) and `nested_skipped`: the distinct keys of
    carriers found only under another carrier, left out of `n`/`of` (0 with
    `nested`; plan 36 §2).
  - `job_agg`, `job_agg_by`, `job_agg_value`, `job_agg_metric`,
    `job_agg_nested` (`1`/`0`) pick it
    (`experiments?top=1&job_agg=median&job_agg_by=field:params.trade_date&job_agg_value=own&job_agg_metric=date.best_value`),
    over the app's `experiment.ui.job_aggregate`; a bad value, or any of
    them without `top` (a tree page included), is a 400. They key the ETag.
    Grouped (`top` with `group`), a group's `job_aggregates` pool its
    outer runs' units (see **Grouped answers** below). Computed from the rollups' per-parent tallies
    (and, for `field:`/`kind:`, per-parent tallies of the runs carrying the
    field, moved on by the index deltas like the rollups), per generation,
    time bucket and aggregate: about 2 ms for 45 outer runs x 16 dates x
    1000 trials after a delta. `declared_progress` is `{done, total, unit,
  rate_per_min}` when the outer run declares one (else null); `progress`
  and `eta_sec` are then its, while `done`/`expected`/`counts`/
  `throughput_per_min` stay run counts. The outer run's `summary` carries
  the same, plus `rolled` by the app's default aggregate (the Overview's KPI
  tile beside the best). A paged answer (`limit`, flat or grouped) carries `main`:
  `{metric, goal}`, the metric every `job` is of (the primary, else the
  alphabetically first metric with a goal), so a page of single runs names
  it too; the web's Best column reads only it.
  - With `match_subtree=1` and a `q`, an outer run matches when it or any run of its
    subtree does. Each row then gets `matched`, and the page gets
    `jobs_matched`/`runs_matched`.
  - `top_q=<query>` keeps the top-level runs passing it by their own fields,
    beside `q` (which `match_subtree` may match over subtrees), flat or
    grouped. Its `ago()` is pinned to the minute like `q`'s; without `top`
    it is a 400. The Live and Review presets and the Outer runs' status
    chips send it. It reads `live_below`: the runs below the row
    still running, waiting or stuck (its rollup's `counts`, settled runs
    left out; 0 for a single run), `running_below`/`stuck_below`, those
    running or stuck alone, `failed_below`/`failed_pct`, the failed and
    lost runs below it and their share in percent (the rollup's
    `failed_pct`: what did not finish), and `lost_below`, the lost ones
    (the rollup's `lost`) — the counts `vmn-exp list --query` and the SDK
    read too ([query fields](sdk.md#the-query-language)), so the command line
    under the board lists the same outer runs.
  - `experiments-facets` returns `jobs`/`singles` counts.
- **`experiments?children_of=<verstr>`** pages that run's direct children
  for [the tree](ui.md#the-tree): `{rows, total, next_cursor, tree_columns, main}`
  (always paged, `limit` <= 1000), filtered (`q`, `status`, `archived`),
  sorted (`sort`/`order`, the `job:*` sorts by the children's summaries
  too) and keyset-paged (`cursor`) like the board, with the same ETag/304.
  - A child with children carries `job`, the outer run row's summary with
    `attention` (`{key: n}`, the runs of its own subtree, itself included,
    each attention query matches; built-in parts only when non-zero) and
    `attention_rank`, plus `split` and `by` (its runs per value, as the
    summary's) when `experiment.ui.split_by` is set. A child without children
    has `job: null` and `attention` when it matches a query itself. Rows keep
    `duration_ratio`.
  - Every row carries `open`: true for a child with children whose subtree
    has attention, or running or stuck runs.
  - `tree_columns` is the app's `experiment.ui.tree_columns`
    (`{<tags.kind value>: [show keys]}`, `{}` when unset).
  - With `match_subtree=1`, `status` and `q` match subtrees: a child is
    kept when it or any run below it passes both, in the children's order
    without them, and carries `matched` (its subtree's passing runs, itself
    included); a child with a passing run below is also `open`. The web
    tree asks this way under the Runs tab's filters.
  - Children orders are cached and moved across index generations like the
    board's, in caches of their own, so opening nodes never evicts the
    board's orders; attention per node is counted once per generation over
    the tree a request reads. An unknown run is a 404, a malformed one a 400,
    as is `children_of` with `group`, `top` or a query reading `comments`.
- **`scope=<verstr>`** keeps that run's subtree, without the run itself. It
  works on `experiments` (flat and grouped), `experiments-columns`,
  `experiments-facets` (which also takes `q`/`status`), `experiments-importance`
  and `experiments-pivot`. An unknown run is a 404.
  - A scoped or filtered `experiments-facets` adds `note_sigs`: the 20 note
    signatures most of its runs logged, `[{sig, runs, count}]` (`count` =
    notes), absent when they logged none. The Runs tab's facet sidebar lists
    them under Notes; a click adds `notes ~ "<sig>"`.
- **Grouped answers** give every group a `clause`, the filter text that
  selects exactly it. With `top=`, groups add `job_counts`, `runs`, `failed`,
  `run_counts` (their outer runs' `counts`, summed), `lost` (their lost
  runs, never in `run_counts`; plan 34 §3) and `job_aggregates`:
  `{metric: pooled}`, the units of all the group's outer runs pooled under
  the rows' aggregate (plan 34 §1). `pooled` has a row's `rolled` fields
  (`agg`, `by`, `source`, `metric`, `goal`, `percentile`, `value`, `n`,
  `of`, `conflicts`, `verstr`, `approx`, `mixed`/`policies`, and for
  `field:`/`kind:` `nested`/`nested_skipped`: a key nested in every attempt
  holding it), plus `from_earlier` and every group aggregate of the pooled values (`mean`,
  `median`, `best`, `min`, `max`, `best10`, `worst10`). `from_earlier` counts
  the units taken from an attempt other than the group's latest. A unit key
  found in several outer runs counts from the latest by start, else
  creation. `by=runs` pools the merged sketches of every attempt: no
  latest-wins, `from_earlier` 0 and no other aggregates. `{}` when no unit
  has a value; the page's `job_agg` (`agg`, `by`, `source`, `metric`,
  `goal`, `percentile`) still names the aggregate, so a header reads `—` or
  `— (no goal)`, never blank (plan 32 §0). The pool reads each outer run's unit list kept with the
  rows' `rolled`, per generation, bucket and aggregate: no subtree walk per
  request. `collapse_all=1` (with `group` and `top`, else a 400) answers the
  headers without rows (one row per group). A `job:*` `sort` needs `top`
  (else a 400): each group's rows take the Jobs order and groups order by
  their first row (`job:started`: the latest attempt's start, newest first).
- **`experiments/{v}/summary`** is the outer run's rollup: counts, `expected`,
  `ended` (its own status succeeded/failed/stuck), `never_started` and `lost`
  (its settled runs, never in `counts`; `done` takes the lost ones, an ended
  run's ETA only its running and waiting ones), progress, throughput, ETA, `metric`, `ranked`, per-metric
  `{goal,n,min,max,mean,best,best_verstr,p10,p50,p90,hist}` (`best` null
  when `goal` is), duration p50/p90,
  failure signatures, `top` (10 best) and a `timeline` (epoch-second buckets
  of `started`/`succeeded`/`failed`, plus `released` where runs were handed
  back and `notes` where runs noted something (each note signature counted
  once, in the minute a run last noted it), sparse; the chart draws releases
  per minute beside completions, not notes yet).
  - `?split=tags.<k>|params.<k>` (default: `experiment.ui.split_by` from conf.yml, else the store
    settings; another field is a 400)
    adds `split` (the field, else `null`) and `by`: per value
    `{key, label, clause, total, counts, done, never_started, lost,
    failed_pct, duration: {n, p50, p90}}`, most runs first, at most 12, then
    one `{key: null, label: "other", other: true, ...}` for the rest. `key`
    is the group key (`∅` = no value, label `(none)`), `clause` the query
    selecting the value's runs (`other`: `<field> not in (...)`). The index
    keeps one tally per (parent, value) for at most 12 values a parent (the
    first in key order; the rest under the parent's `other`), moved by the
    same deltas as the rollup. A value some parent may hold under its `other`
    is never listed: its runs count under `other`, so a listed value's
    numbers are always its whole subtree's.
- **`experiments/{v}/failures?limit=`** returns the clusters. Both outer run
  endpoints 404 for a run without children, and answer 304 on an early ETag.
- **`search?text=&limit=`** is ⌘K's run search over every run. It ranks exact
  `@N`, then verstr prefix, then name prefix, then a substring in any indexed
  field.
- **`events?scope=<verstr>|top`** is a Server-Sent Events stream of
  `change` events (`{generation, changed: {rows, jobs}}`), coalesced to one a
  second, with a heartbeat every 25 s. It is 404 without a background
  refresher and 503 past 256 streams.
- **`POST actions/exp_archive|exp_unarchive|exp_tag`** also take
  `{scope, q, status, archived}` instead of `verstrs`. `dry_run: true`
  returns `{count, sample}`. Otherwise the action runs as a job in batches of
  500, with `progress: {done, total}`.

### Experiment status fields

Every row of `.../experiments` and the run detail carry:

| Field | Meaning |
|---|---|
| `status` | `created` / `running` / `stuck` / `succeeded` / `failed` (derived, never stored) |
| `exit_code` | the command's exit code once finished, else `null` |
| `started_at` / `finished_at` | ISO-8601 timestamps |
| `heartbeat` | last heartbeat refresh |
| `stale_sec` | seconds since the last proof of life (the fresher of the heartbeat and the store's write time of `run_state.yml`) |
| `duration_sec` | wall-clock run time once finished (elapsed while running: the `duration` column reads `10m (running)`); `null` for a run that stopped without a recorded end (stuck, failed unfinished), which then sorts after the known durations |
| `duration_at_least_sec` | that run's lower bound: its last proof of life (as `stale_sec`) minus `started_at`, else `null`. The `duration` column reads `≥ 3h (stuck)` |
| `queue_sec` | seconds from creation (`timestamp`) to `started_at`, never below 0; `null` until the run starts |
| `duration_ratio` | board rows only: `duration_sec` over the median duration of its siblings, the finished (succeeded or failed), unarchived runs with the same parent and the same value of `experiment.ui.split_by` (none: the parent alone; the median at P3's rank as its sketches report it, within 1 %). A running run uses its elapsed time. `null` with fewer than 3 finished siblings (the run counted), without a parent, and for a waiting, stuck or end-less run. The board's `ratio` column reads `3.1× siblings`; `q=duration_ratio > 3` finds the outliers |
| `pid` / `host` / `command` | what ran, where |
| `last_metric_at` | when a metric was last logged, to spot a run that is alive but not progressing |
| `parent` / `children` | verstrs linking outer and inner jobs |
| `kind` | `outer`, `inner` or `single` |
| `depth` | nesting depth, for indenting the list |
| `settled` | `never_started` (created), `lost` (stuck, or released) or `outlived` (running, counted as running) for a run under an outer run that ended, else `null`: derived, the run's own `status` stays |
| `tree_status` | rollup over the run and its subtree (`failed > stuck > running > created > succeeded`); a container outer's own `created`, a `never_started` and a `lost` run are left out (only a non-zero exit makes it `failed`; `lost_below` counts the lost ones), an incomplete sweep that has not ended adds `created` |
| `sweep_planned` / `sweep_trials` | a sweep outer's planned trials (grid size, else `run_cap`) and the trial slots its inner runs fill; absent for other runs and uncapped random/bayes sweeps. While `sweep_trials < sweep_planned` the UI reads `16/20 · incomplete`, and the detail's `status.fleet.expected` is the planned size |
| `signal` / `end_reason` | the signal that ended (or released) the run (`SIGTERM`); `stopped` for an early-stopped sweep trial, `released` for a run handed back unfinished (`run.release()`, status `created`) |
| `released_at` / `resume_count` | the run's last release (kept once it is reopened) and how many times it was reopened (`start_run(run_id=)`), else `null` |
| `error_summary` | `Type: message` of a failed run's recorded `error`, else `null` |

The run detail also groups them under a top-level `status` object, which also
carries `error`: the run's full `error` mapping (`type`, `message`,
`traceback`, `source`, `output_tail`) or `null` — never on list rows. An
outer run's `status.fleet` is `{expected, counts}` (no `children`: its runs
are the outer run page's Runs tab). The list
takes `status=running,stuck` (comma-separated) to filter:

```sh
curl -H "Authorization: Bearer $VMN_UI_TOKEN" \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments?status=running,stuck"
```

### Server meta and roles

`GET /meta`:

| Field | Meaning |
|---|---|
| `version` / `vmn_exp_version` | vmn's version, the installed `vmn-exp` package's (`null` when not installed as a package) |
| `read_only` | `--read-only` |
| `mode` | `configured` with `--config` or a control plane, else `standalone` |
| `control_plane` | whether a control plane (API tokens) is configured |
| `auth` | `{enabled, token, oidc, login_url}`: the sign-in methods offered (`login_url` is `/auth/login` with OIDC, else `null`); never a secret |
| `principal` | `{id, name}` of the caller, or `null` |
| `role` | the caller's role in `*`, or `null`. With auth on, `null` means no global role (per-workspace roles may still apply); with auth off, everything is allowed |

Each `/workspaces` item carries `role` (`viewer`/`editor`/`admin`, the `*`
role included), `null` with auth off or no role there.

### Git context

`GET /workspaces/{ws}/git` (git workspaces only: a store workspace is 400):

```json
{"branch": "main", "detached": false, "head": "<40-hex>", "head_short": "e71c74d", "dirty": true, "store": ".vmn/store"}
```

One `git --no-optional-locks status --porcelain=v2 --branch
--untracked-files=no` (2 s timeout), so it never takes `index.lock` and
untracked files are not dirty. Detached: `branch: null, detached: true`. On a
failure it still answers 200 with `branch`/`head`/`head_short`/`dirty` `null`
and an `error` (the first stderr line, or `timeout`). Cached 5 s per workspace.

The topbar's breadcrumb root shows the workspace and `branch @ head_short`
(plus `dirty`); `store` and the checkout path sit behind its Data source
button, not in the trail. When the workspace is named after its app, the
trail leaves the app crumb out.

### Status counts and rollup

`GET ws/{ws}/apps/{app}/experiments-status`:

```json
{"total": 53,
 "counts": {"created": 0, "running": 2, "stuck": 1, "succeeded": 41, "failed": 9},
 "never_started": 0, "lost": 0, "failed_recent": 1, "rollup": "stuck"}
```

Counts the non-archived runs by derived status (all five keys always present).
A run an ended outer run settled counts as `never_started` or `lost` instead,
never in `counts` (`total` holds every run), so a lost run raises no `stuck`;
an `outlived` one (still running) stays in `counts.running`.
`failed_recent` counts failures that finished within the last 24 hours. `rollup` is
`stuck` if any run is stuck, else `failed` if `failed_recent > 0`, else
`running` if any runs, else `null`. A known app with no runs answers zeros; an
unknown app is a 404 `{"detail", "code": "app_not_found"}`, checked against the
checkout (`.vmn/<app>/conf.yml`) and the store (any run or snapshot record),
not the cached app list. ETag/304, accurate to the hour for `failed_recent`. The same
counts, the attention parts and per outer run rollups are Prometheus gauges on
[`/metrics`](server.md#prometheus-metrics).

With attention queries configured (`experiment.ui.attention`, at most 8, see
[server.md](server.md#app-settings)), the summary carries a count for each,
after the built-in stuck and failed-in-24h parts the strip shows first:

```json
"attention": [{"key": "unstable", "label": "unstable", "level": "error", "count": 4,
               "q": "tags.health = \"unstable\""}]
```

A count is the length of the board's own cached order for `q` (non-archived
runs), so a time-free query moves with the index deltas and an `ago()` one is
rebuilt at most once a minute (about 0.2 s at 100k runs). A query that does
not compile counts `null` and carries `error`. `?scope=<verstr>` answers the
whole summary over that run's subtree, without the run (an outer run's page;
counts and recent failures from its rollup; 404 for no such run). On the
Outer runs view (`experiments?top=...`) each row's `job` carries `attention:
{key: n}` (the runs of its tree, itself included, each query matches, none
under an archived run) and
`attention_rank`, which `sort=job:attention` orders by.

One part is built in, configured queries or not, and comes before them:
`{"key": "outlived", "label": "outlived their outer run", "level": "warn",
"q": "settled = \"outlived\""}`, the runs still running under an outer run
that ended. It is counted from the live rows (never a board order) and, in
the summary and in a row's `job.attention` alike, present only while it
counts any, so an app with none and no queries has no `attention`. A list `q` with
`ago()` is pinned to the minute, so its ETag moves with the clock.

The unscoped summary also lists the app's [team views](ui.md#saved-and-team-views)
(`experiment.ui.views`, conf.yml over the settings), present only when it has
some; every app page already reads this status (and the browser keeps it
across reloads), so a page knows its default view at first paint:

```json
"views": [{"name": "health", "page": "runs", "search": "?show=t%3Ahealth", "default": true}]
```

Likewise `failed_pct_threshold`, the app's `experiment.ui.failed_pct_threshold`
(the Outer runs failed chip's [≥ N% failed](ui.md#outer-runs-and-the-outer-runs-page)),
present only when it is not the default 5.

With background refresh (`vmn-exp ui`), the summary also carries how fresh
the app's index is, read without I/O, so a dashboard or a load balancer sees
an index that serves old data or stopped keeping up:

```json
"freshness": {"as_of": "2026-10-22T19:44:00.120000+00:00", "refreshing": true,
              "refresh_running_sec": 125, "phase": "full_listing", "progress": 0.45,
              "refresh_failing": false, "last_error": null, "stale_after_sec": 300}
```

- `as_of`: the wall time the last completed refresh started (`null` before
  one). It persists in the index file (at most once a minute), so a restarted
  server serving its persisted rows says they date from its last refresh.
- `refreshing` / `refresh_running_sec`: a refresh is running, for how long
  (`null` when none).
- `phase`: what that refresh does — `full_listing` (every record's files),
  `journal` (a store's journaled sweep: hinted and live records), `listing`
  (a checkout's names-only listing), `loading_new` (reading the new or changed
  records it found), else `idle`. `progress` (0..1, else `null`): how far an
  S3 full listing's walk is among the index's known keys, or the share of new
  records read. A store app's full listing runs behind serving (see
  [server.md](server.md#how-the-cache-stays-fresh)): between its refreshes
  `phase` stays `full_listing` with the share of records listed as
  `progress`, and `journal` while the app catches up on the change journal
  (a replay after a restart, an overflow, re-reads queued).
- `refresh_failing`: the refresh is failing (`last_error` is its streak's
  last error), its thread is gone, or it has run past 10 minutes (stuck).
- `stale_after_sec`: the age past which the dashboard warns — conf
  `experiment.ui.stale_after_min` of a checkout's app, else the app's
  [store settings](server.md#app-settings) (default 5).
- `unreadable` (absent when none): `{"count": 12, "store_errors": 12,
  "last_error": "ClientError('An error occurred (SlowDown) ...')"}` — the
  records the index set aside unread, retried 60 s later doubling to 10 min:
  `store_errors` of them failed on the store (a throttled, refused or reset
  read), the rest on their own content; `last_error` is the latest failure's
  short repr. The refresh succeeds around them, so this is the only sign of a
  throttled store; a new record stays out and a known one keeps what the
  index had.

Its times count by the minute in the ETag, and what a refresh does only while
the data is stale or the refresh failing (a fresh index's once-a-second
refreshes leave the ETag alone). The dashboard shows a banner under
the topbar, and the boards' count line a short form, when the data is older
than `stale_after_sec` or a refresh runs on data older than that ("Showing
data as of Oct 22 19:44 UTC (4d old). Syncing with the store — listing runs,
~45%. New runs will appear when it finishes."), or when the refresh is failing
("Data is 4d old and the background refresh has not completed for 25m
(last error: …)"); none once a refresh published fresh data. Unless the
refresh is failing, runs set aside unread add a warning to it, or make one
on fresh data ("12 runs could not be read (the store is throttling:
SlowDown); retrying."). It polls the
status every 2 s while a refresh runs on stale data. The refresher heals
itself: an error in any refresh step is logged (a WARNING with the traceback
when a failure streak starts, every 10 minutes while it lasts, and when it
recovers) and never ends its thread; a refresh or journal thread that ended
anyway is restarted by the next request (an ERROR); a refresh running past
10 minutes is warned about once. S3 calls time out (10 s connect, 30 s per
read) and retry in botocore's adaptive mode (a throttling store's `SlowDown`
slows the client down), and at most 64 run at once per key prefix (a
store area and its scope, e.g. `<root>/runs/<app>`; S3 throttles per prefix;
`VMN_EXP_S3_PREFIX_CONCURRENCY` sets another cap, a call made inside another
call's slot takes none); a refresh or journal tick that failed is retried
`interval_sec` later doubling up to 60 s, and a record the store failed to
read is set aside and read again after 60 s doubling to 10 min.

`GET ws/{ws}/apps-status` answers `{"<app tag>": <the same summary>, ...}` for
every app of the workspace in one request (tags use `-` for `/`), memoized
like the per-app route; ETag/304.

### Filtering with a query

`q` is an expression over row fields, metrics and params in the
[query language](sdk.md#the-query-language) that `list_runs(query=...)` and
`vmn-exp list --query` take:

```sh
curl -G -H "Authorization: Bearer $VMN_UI_TOKEN" \
  --data-urlencode 'q=metrics.loss < 0.5 and params.optimizer = "adam"' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments"
```

`q` and `status` combine with **and**. Filtering happens before paging, so
`total` counts matches. An invalid query is a 400 carrying the parser's
message and offset (`unknown field 'statuz' at offset 0`).
`status = "stuck"` matches a run's own status, so it also holds the runs an
ended outer run left `lost`; `status = "stuck" and settled != "lost"` is the
`stuck` that `experiments-status` counts (`!=` matches a run with no `settled`).

A page (`limit` set, flat or grouped) that matches nothing carries `hints`
when one of its `<row field> = <value>` terms (`q` or `top_q`, never under
`not`) names a value some run holds as `tags.<field>` or `params.<field>`:
`kind` is the built-in row kind, so `q=kind = "launch"` answers
`"hints": ["kind = \"launch\" matches nothing; did you mean tags.kind?"]`. They
come from the facet counts, never a pass over the rows; the web shows them
under the query bar and `vmn-exp list --query` prints them to stderr. The web
page's own URL parameters `view`, `kind`, `tab` and `sel` are a 400 on any API route
(`view is a web page parameter; use top=jobs or q=…`) instead of being ignored.

While the app's index is still loading (a cold load, an upgrade re-deriving
its rows), every answer built from it (this list flat, `top=`, grouped or
`children_of=`, `experiments-columns`, `-facets` and `-pivot`, a job's
`summary` and `failures`, `search`, `baseline` and `experiments-baselines`) carries
`"indexing": {"loaded": N, "total": M}` (`total` null before the store has
named its runs), as `experiments-status` does: its rows are some of the app's,
not all. Its ETag follows the load, so a cached loading answer never outlives
it; the web shows `indexing N% — results incomplete` on the board and the
outer run's page.

### Paging, sorting and order

- `offset` and `limit` (at most 1000) page the list; with `limit` the answer is
  `{"rows": [...], "total": N}`, without it a plain list of at most 1000 rows.
  `last=N` keeps only the N most recent runs before sorting and paging.
- `sort` is a metric name, `timestamp`, `started_at` or `finished_at` (dates
  sort newest first). `order=asc|desc` overrides the direction the metric's
  goal implies; runs without the metric stay last either way.
- `sort` also takes any other row field (`duration_sec`, `queue_sec`,
  `duration_ratio`, `stale_sec`, `status`, ...), `tags.<k>` or `params.<k>`
  (plan 28 FS): numbers (bools as 0/1) before strings, ascending unless
  `order=desc`, runs without a value last either way. These orders are cached
  and moved across index generations like the metric orders; a running run's
  `duration_sec`/`duration_ratio` place it again per time bucket. The board's
  `queue`/`duration`/`ratio` columns sort this way.
- `archived=1` includes archived runs, which `.../experiments`,
  `-columns`, `-importance` and `-facets` otherwise leave out (and out of
  `total`).
- Each response carries an `ETag` (index generation, parameters and, while runs
  are live, the status bucket); send it back as `If-None-Match` and an
  unchanged poll is an empty `304`.

The goal comes from the app's effective metrics schema,
`GET .../metrics-schema`: conf.yml's `experiment.metrics` over the app's
[store settings](server.md#app-settings), plus the `goal`/`hidden`/`chart` runs
declare for names neither has. A conf/settings goal (exact or glob) always
wins; else the one goal the app's runs (archived ones too) declare. Runs
declaring different goals give no goal: the entry reads `goal_conflict: true`
and `goals: {min: <runs>, max: <runs>}` (see
[Metrics schema](experiments.md#metrics-schema-sorting--goals)); a store
workspace has no conf.yml, only the settings and the runs' declarations. Each
metric the app's runs log that a glob (`val_*: {goal: max}`) gives a goal also
appears under its own name with that goal, so a client reads goals by exact
name. A metric with no goal there has none: the web never guesses one from
its name. It also decides which metrics the
dashboard hides by default (the column picker and a collapsed "hidden metrics"
section on the run page show them).

```sh
curl -H "Authorization: Bearer $VMN_UI_TOKEN" \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments?sort=loss&order=asc&limit=50"
```

### Grouped runs

`GET .../experiments?group=<field>` answers groups instead of a page. The
field is a link between runs, `parent`, `forked_from`, `rerun_of` (the run
pointed at heads the group and is not one of its rows) or `code_verstr` (the
code state), a row field: `branch`, `status`, `root` (the top-level outer run), `tags.<key>`,
`params.<key>`,
or an ancestor's field, as the [query language](sdk.md#the-query-language) reads
it: `up.params.<key>`, `up.tags.<key>`, `up.name`,
`up(tags.kind = "study").params.<key>` (the clause is `<field> = <value>`,
`<field> = null` for the `(none)` group). A change to an ancestor's params,
tags or name regroups the runs below it.

```
{"groups": [{"key", "label",
             "target": {verstr, idx, name, status, tree_status, metrics} | null,
             "loose": false,
             "counts": {total, running, waiting, done, failed, stuck},
             "aggregates": {"<metric>": {mean, best, median, min, max, n, goal}},
             "rows": [...], "rows_total": 5, "rows_unfiltered": 16}],
 "total_groups": 3, "total_rows": 48, "running": 2, "aggregate": "mean",
 "metric": "loss", "goal": "min"}
```

- Each aggregate names its metric's `goal` (`null` without one: no `best`,
  no direction).

- `target` is the header run of a `parent`/`forked_from`/`rerun_of` group. A
  target missing from the index (pruned, another app) groups under its verstr
  with `target: null` and the label `<verstr> (not found)`. Runs without a
  value form one group, always last, labelled `(none)`. Its `key` is `∅` (U+2205), which no value's key equals: a value
  whose text starts with `∅` is keyed with it doubled (`∅x` -> `∅∅x`), so a
  param literally set to `(none)` is a group of its own. Every group carries
  `loose`, true only for that group of a link grouping (`parent`,
  `forked_from`, `rerun_of`): the runs with no link minus those heading a
  group of the grouping (after the filters), so each run shows once; its
  counts, aggregates, `rows_total` and `rows_unfiltered` cover those runs,
  and it is absent when there are none. `total_rows` and `running` count
  every passing run. The board shows a loose group's rows without a header.
- Filters (`q`, `status`, `archived`) select rows; a group shows when one of
  its rows passes, and its counts and aggregates cover the passing rows.
  `rows_total` counts its passing rows, `rows_unfiltered` its rows with the
  same `archived` setting but without `q`/`status` (equal when no filter is
  set; the board's `5 of 16`). Only `q` and `status` are dropped: the web
  client sends its branch and search filters inside `q`, so they are dropped
  too. A link group keeps its `target` even when the
  target fails the filter. A `rerun_of` group's aggregates include the
  original's own value.
- `running` counts the running rows of every group after the filters, not
  only the page's, so a client can poll while any run is live.
- `aggregates` cover each metric's finite values, by each run's summary
  policy; `best` follows the metric's goal and is null without one. When
  some rows' runs override conf.yml's summary (a run's own `define_metric`
  beats it), the aggregate carries `mixed: true` and `policies`
  (`{override: runs}`), and the header cell's title adds `2 runs use min`.
- `sort`/`order` order rows within a group as on the flat list. Groups order
  by `agg=mean|best|median|min|max` of the sort metric (`best` without a goal
  has no value; groups without a value after the others); the page names
  that `metric` and its `goal` (null without one), and by their first
  row for a date or no metric sort. `sort=c:total|c:waiting|c:running|c:done|c:failed`
  orders groups by that count instead (`waiting` = created, `done` =
  succeeded, `failed` = failed + stuck; the board's Sort groups row),
  most first unless `order=asc`; ties keep the default group order, rows
  within a group keep their default order (no sort), and the no-value group
  stays last. Without `group=`, a `c:*` sort is an unknown metric like any
  other (no row carries it). `agg` defaults to
  `experiment.ui.group_aggregate` of the conf.yml the app reads on the
  checkout's branch (its branch conf when there is one, as `vmn` resolves
  it; a detached HEAD, as in CI, counts as the branch `vmn stamp` resolves
  it to: the CI env's branch, else the branch last checked out, else the one
  branch at or containing it; no branch reads the app's conf.yml), else the
  app's store settings, else `mean`; `aggregate` names what it
  resolved to, and every aggregate is in the payload either way.
- `offset`/`limit` page groups (default and at most 50); `rows_per_group`
  (default 10, 1..100) caps each group's `rows`, lowered so a page holds at
  most 5000 rows. Values out of range are clamped, not refused.
  `group_key=<key>&offset=&limit=` answers that one group with its rows paged
  like the flat list (404 for an unknown key).
- An unknown field or aggregate, or `last`, is a 400. Groupings are kept
  per index generation and moved along with it, so a grouped page costs
  about what a flat one does.

```sh
curl -H "Authorization: Bearer $VMN_UI_TOKEN" \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments?group=parent&sort=loss&agg=best&limit=50"
```

### Columns for whole-set charts

`GET .../experiments-columns?keys=...` answers a few values for every matching
run, so a chart plots all of them, not the loaded page:

```sh
curl -G -H "Authorization: Bearer $VMN_UI_TOKEN" \
  --data-urlencode 'keys=metrics.loss,params.lr,status' \
  --data-urlencode 'q=metrics.loss < 0.5' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments-columns?sort=loss"
```

```json
{"verstrs": ["...r0003", "...r0001"], "idx": [4, 2],
 "columns": {"metrics.loss": [0.1, 0.3], "params.lr": [0.01, "auto"], "status": ["succeeded", "running"]},
 "total": 2}
```

- `keys`: comma list of `metrics.<k>`, `params.<k>`, `up.<field>` (an
  ancestor's value, as in a query: `up.params.trade_date`), `timestamp`, `status`,
  `branch`, `name` (the run's name, else its note) and `group:<field>` (the
  run's group key on the board grouped by `<field>`, as the list's `group=`
  takes it, `∅` for no value); anything else is a 400.
  Columns align with `verstrs` and `idx` (the `@N` index).
- Metric values are numbers or `null`; params are verbatim.
- `q`, `status`, `sort`, `order`, `archived`, `scope`, `top`, `top_q` and
  `match_subtree` work as on the list, in the same order, so a select-all
  on an Outer runs, Live or Review page takes the outer runs it shows. `limit` (default 20000, at most 50000) caps the rows; `total` counts
  every match. ETag/304 like the list.

### Parameter importance

`GET .../experiments-importance?metric=<m>` answers which params drive a metric
over the matching runs (the leaderboard's **Importance** view; click a param
for its scatter or per-value mean table):

```sh
curl -G -H "Authorization: Bearer $VMN_UI_TOKEN" \
  --data-urlencode 'q=status = "succeeded"' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments-importance?metric=loss"
```

```json
[{"param": "lr", "importance": 0.91, "correlation": 0.95, "spearman": 0.94, "kind": "numeric", "n": 240},
 {"param": "opt", "importance": 0.06, "correlation": null, "spearman": null, "kind": "categorical", "n": 240}]
```

- Sorted by `importance` (a random-forest share summing to 1); `correlation`
  (Pearson) and `spearman` are `null` for categorical params; `n` counts runs
  with both the param and the metric; single-valued params are left out. See
  [`vmn-exp importance`](experiments.md#importance).
- Takes `q`, `status`, `archived`. `metric` is required; a metric no visible
  run carries, or a bad `q`, is a 400; no matching run answers `[]`.
- Past 5000 matching runs a deterministic sample of 5000 is scored. ETag/304.

### Pivot heatmap

`GET .../experiments-pivot?rows=<field>&cols=<field>` crosses the matching
runs by two [group fields](#paging-sorting-and-order) (`tags.<k>`,
`params.<k>`, `up.*`, `branch`, `status`, `failure_sig`, a link, or `root`):
one cell per pair of values (plan 28 N2; the outer run's Overview card and
the reports' [`pivot` panel](reports.md#panels-vmn-panel-blocks)).

```sh
curl -G -H "Authorization: Bearer $VMN_UI_TOKEN" \
  --data-urlencode 'match=tags.health = "unstable"' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/experiments-pivot?rows=tags.trade_date&cols=tags.group&cell=share&scope=0.4.0-dev.abc"
```

```json
{"rows": [{"key": "2024-06", "label": "2024-06", "n": 240, "clause": "tags.trade_date = \"2024-06\""}],
 "cols": [{"key": "BCA", "label": "BCA", "n": 60, "clause": "tags.group = \"BCA\""}],
 "cells": [[{"n": 24, "value": 0.125, "hits": 3,
             "clause": "tags.trade_date = \"2024-06\" and tags.group = \"BCA\""}]],
 "total": 240, "rows_total": 1, "cols_total": 1, "cell": "share",
 "match": "tags.health = \"unstable\"", "metric": null, "agg": null, "goal": null}
```

- `cell=count` (the default): `value` is the cell's runs. `cell=share&match=<query>`:
  the share of them matching the query (`hits` of `n`). `cell=agg&metric=<m>&agg=`
  `mean|best|median|min|max` (default the app's group aggregate): the aggregate of
  the metric's finite values, `null` when none carries it; `goal` is the
  metric's, and `best` without one is `null` in every cell. A cell some of
  whose runs override conf.yml's summary carries `mixed: true` and `policies`
  (`{override: runs}`); the heatmap marks it `*`, its title adding `1 run uses
  min`. The Jobs view's best, the job page's best tile and the baseline card's
  metric rows say the same of a job rollup's runs.
- Takes `scope`, `q`, `status`, `archived`. A bad field, cell or query is a 400.
- Each axis keeps its 200 (rows) / 50 (cols) most common values, ordered by
  value (numbers before text, `(none)` last); `rows_total`/`cols_total` count
  them all. An empty cell is `null`. Headers and cells carry the `clause`
  selecting their runs (`null` when the language can't say the value).
- Kept per index generation; within a `scope` with nothing live under it (a
  settled launch) the pivot is kept until a run of its subtree (or an
  ancestor an `up` field reads) changes, so a finished launch's heatmap is
  built once per process and keeps its ETag (a 304) across generations
  (`ui/pivot_cache.py`). Otherwise ETag/304 like the list.

### Baseline compare

`GET .../experiments/{verstr}/baseline` compares an outer run with its
baseline (plan 28 N3): the outer run's Overview card and the chip on its
header and its Outer runs row.

- **Which run.** `?to=<verstr>` (any other outer run), else the latest peer
  (same parent; top-level for a top-level run) tagged `baseline=true`, else
  the latest peer that ended (succeeded, failed or stuck) before it was
  created, both with equal values on the match fields. The rule is
  conf/[settings](server.md#app-settings) `experiment.ui.baseline: {match:
  [<field>...], children_by: <field>}` (fields `params.<k>`/`tags.<k>`);
  `?match=params.a,params.b` (empty: match nothing) and `?by=<field>`
  (empty: no pairing) override it. The rule's `differ: [<field>...]`
  (plan 34 §2) also skips every peer equal to the run on one of those fields
  or missing one (as does a run missing one: missing is never different), so
  a relaunch is not compared with the earlier attempt of the same launch; the
  body names them in `differ`.
- **Trainings.** The rule's `pool_by: <field>` (plan 36 §3, e.g.
  `tags.launch_id`) compares a run through its training: the outer runs
  beside it sharing its value, the latest attempt first (by start, else
  creation), as a [grouped header](ui.md#outer-runs-and-the-outer-runs-page) pools them. The
  peers are the other trainings, chosen by `match`/`differ`, pin and "ended
  before" on each training's latest attempt; `baseline` is the chosen
  training's latest attempt. The children pair over each side's attempts,
  a key taken from the latest attempt holding it, and `rolled` compares both
  trainings' pooled units; the rollup deltas stay the two latest attempts'.
  So a finalise-only attempt, with no dates of its own, still gets its
  training's dates compared. A run without the field has no baseline
  (missing is missing). The body adds `pool_by` (always) and `pool: {by,
  attempts, baseline_attempts}` (both sides' verstrs, the latest first); the
  chip carries `pool_by` and the web adds `· pooled by tags.launch_id`, the
  card `pooled by tags.launch_id (2 attempts vs 3)`.
- **What.** Per goal metric of the rollup (the primary included) its `best`
  and `median`, then `failed_pct`, `duration_p90`, each attention query's
  share of the subtree (`attention`, with both counts), and the metrics
  both outer runs log themselves (`own`, at most 20; e.g. a cost per date
  logged at close). Each is `{value, baseline, delta, better}`, `better`
  following the goal (failures, durations and attention shares: lower); a
  metric without a goal has no `best` and its `better` is null.
- **Children.** With `children_by`, the two outer runs' direct children
  pair by that field's value (a retried value: its latest run), in key
  order (`pairs`, the first 200 listed, of `pairs_total` values the outer
  run holds; the chip counts them all): per pair the child's value on both
  sides, the delta, and `done`. The value is the Outer runs row's: the
  app's `job_aggregate` metric (default the main one), each child's own or
  its subtree's best by its `value` (default `best`), the same source on
  both sides and never the other as a fallback. A value either side lacks
  leaves the key unpaired; the chip's `paired` of `total` counts them (`5
  of 39 paired`).
- **Aggregate.** `rolled` is the delta of both outer runs' `rolled` (the
  app's default aggregate) with its `agg`/`by`/`source`/`metric`/`goal`/
  `percentile`.
- **The chip** counts the finished pairs worse than the baseline's worst
  decile (its children's `p10` of a higher-is-better main metric, `p90` of a
  lower-is-better one): `▼ best_value from 2024-12 (5 of 41 trade_date values
  worse than the baseline's p10)` (`state` `worse`), `▲`/`=` when none is
  (`better`/`same` by the median delta), `pending` before any has finished,
  so it shows while the launch still runs. An outer run holding no
  `children_by` run at all is `none`: `best_value: this attempt has no
  trade_date runs of its own` (with `pool_by`: `this training has no
  trade_date runs in any attempt`), never "no value finished yet". Without `children_by` it is the
  `rolled` value's change (`▼ best_value 0.81 (baseline 0.92)`, `▼ median
  best_value 0.65 (baseline 1)` for another aggregate). A main metric
  without a goal (`goal: null`) has no chip: its pairs carry the deltas with
  `better: null` and no `worse` mark.

```json
{"verstr": "0.4.0-dev.abc", "match": ["params.table_name", "params.model_type"], "differ": [],
 "by": "params.trade_date", "values": {"params.table_name": "fx", "params.model_type": "nn"},
 "baseline": {"verstr": "0.3.0-dev.def", "idx": 12, "name": "wf_41aa", "status": "succeeded",
              "source": "latest", "started_at": "…", "finished_at": "…"},
 "metric": "best_value", "goal": "max",
 "metrics": {"best_value": {"goal": "max",
                            "best": {"value": 1.21, "baseline": 1.3, "delta": -0.09, "better": false},
                            "median": {"value": 0.9, "baseline": 0.8, "delta": 0.1, "better": true}}},
 "failed_pct": {"value": 5.0, "baseline": 2.0, "delta": 3.0, "better": false},
 "duration_p90": {"value": 7200, "baseline": 3600, "delta": 3600, "better": false},
 "attention": [{"key": "unstable", "label": "unstable", "level": "warn", "q": "…", "count": 12,
                "baseline_count": 3, "value": 0.12, "baseline": 0.03, "delta": 0.09, "better": false}],
 "own": {}, "pairs_total": 41,
 "pairs": [{"key": "2024-12", "label": "2024-12", "verstr": "…", "idx": 102, "baseline_verstr": "…",
            "value": 0.2, "baseline": 1.0, "delta": -0.8, "better": false, "done": true, "worse": true}],
 "chip": {"state": "worse", "metric": "best_value", "from": "2024-12", "worse": 5, "of": 41,
          "quantile": "p10", "threshold": 0.94, "text": "▼ best_value from 2024-12 (…)"}}
```

- No baseline found: `baseline` and `chip` are null and nothing is compared.
  A run without children (or an unknown run, or a `to` that is no outer run)
  is a 404; `to` the run itself or a bad field a 400.
- `GET .../experiments-baselines?v=<verstr>&v=...` (at most 200, `match`/`by`
  as above) answers `{"chips": {verstr: chip with its "baseline", or null}}`:
  what a page of the Outer runs view shows, in one request per page rather
  than one per row, computed for the shown runs only (board pages carry no
  baseline).
- Kept per index generation and time bucket; a pair with nothing live in
  either subtree is kept until a run of either changes, with its own ETag (a
  304 across generations), so a finished launch and its baseline are
  compared once per process (`ui/baseline_views.py`); attention shares are
  kept per generation beside it. Otherwise ETag/304 like the list.

### Facets

`GET .../experiments-facets[?archived=1]` answers the filter and Group by
vocabulary, each list sorted (`metric_keys` includes numeric params; `total`
counts all runs), with an ETag. `param_values` is each param's number of
distinct values, capped at 21 (the board's Group by menu offers a param only
with at most 20); `parented` counts the runs with a parent (the board groups
by parent run by default when it is non-zero):

```json
{"branches": ["feat/x", "main"], "metric_keys": ["acc", "loss"], "param_keys": ["lr", "opt"],
 "tag_keys": ["team"], "param_values": {"lr": 21, "opt": 3}, "parented": 40, "total": 5000}
```

### Run detail is bounded

`GET .../experiments/{verstr}` costs the same however long the run logged.
Query params: `max_points` (default 2000, at most 20000), `keys=loss,acc`
(only those series), `series=0` (no series), `include_log=1` (whole log),
`x=<metric>` ([custom x axis](#custom-x-axis)), `step_min`/`step_max`
([zoom](#zoom-and-many-keys)).

| Field | Meaning |
|---|---|
| `log_tail` | the newest 200 log entries |
| `log_total` | how many entries the log holds |
| `log` | same as `log_tail`, or the whole log with `include_log=1` |
| `series` | each metric thinned to at most `max_points` with min/max buckets (spikes survive; first and last kept). At most 200,000 points per response: with many metrics `max_points` is lowered |
| `series_total` | `{metric: points before thinning}` |
| `step_metrics` | `{metric: x metric}` for every metric that declares a `step_metric` |
| `hidden_metrics` | the run's metrics marked hidden, sorted |
| `metric_charts` | `{metric: "bars"\|"table"}` for the run's metrics whose `chart` hint is not a line (the run's `define_metric`, else the schema), absent when none; the run page draws them that way |
| `metric_summary` | `{metric: {last, min, max, first, mean}}` for metrics logged more than once |
| `logged_params` | the params the run also logged as metrics (their `metrics` value is the logged one); any other param in `metrics` is a folded param |
| `outputs` | the run's outputs (see [Lineage](#lineage)) |
| `rerun_of` | the run this one reruns, if any |
| `patches` | which patch kinds the snapshot holds |
| `media` / `tables` / `histograms` | logged images, tables, histograms per name, one item per step ([Media](#media)); `histograms` is `{}` once they would serve more than 100 steps in all |
| `histograms_total` | `{name: steps logged}` for every histogram name |
| `compacted` | whether every metrics writer of the run has its compacted `.vmx` (the UI shows a "not compacted" badge otherwise) |
| `output_tail` | failed/stuck runs only: `{lines, truncated}`, the last 40 lines of `outputs/output.log` (one range read of at most 16 KB; a partial first line is dropped, a `\r`-rewritten line keeps its last rewrite), `null` without one |
| `last_step` | failed/stuck only: `{step, of}`, the highest step of the metrics' newest points; `of` = numeric `params.epochs`, else `params.max_steps`, else `null`; `null` without a stepped metric |
| `last_good` | failed/stuck only: `{verstr, idx, name}` of the latest earlier succeeded run of the same command (unarchived), else `null` |
| `idx` / `name` | the run's `@N` index and its name (from its index row, else `name` from its metadata); `null` when unknown |

Page older entries with `.../log`. A live run's poll parses only the log bytes
appended since the last one. Detail and log carry an `ETag` and
`Cache-Control: no-cache` (304 when unchanged).

### Run code: patch and baselines

`GET .../experiments/{verstr}/patch?max_bytes=200000` is `vmn-exp show
--patch --json`'s `patch` object plus `files`:

```json
{"text": "=== working_tree ===\ndiff --git ...", "truncated": false,
 "files": [{"path": "train.py", "added": 3, "removed": 1}]}
```

`files` counts each path's hunk lines in the served (possibly truncated) text,
summed over its sections; dep paths read `deps/<dep>/<path>`. Without text it
is `{"text": null, "reason": "no_code"|"code_missing"|"untracked_only", "files": []}`
(`untracked_only` adds `untracked_files`). With text, a run that captured
untracked files also carries `untracked_files` (at most 200 paths) and
`untracked_total`, or `untracked_files: []` with `untracked_unreadable: true`
when its tarball cannot be read; without a tarball these keys are absent.
Listing the names reads the tarball on each uncached request; the ETag makes
later ones 304. `max_bytes` must be >= 1 (400) and is
capped at 10 MB. The ETag is the run's code identity, so a 304 never loads the
code object (none on `code_missing`, whose object may still be pushed).

`GET .../experiments/{verstr}/baselines` names the runs the Changes card can
diff against, from the index snapshot (no git, no lock). Each key is present
only when it exists, each `{verstr, idx, name, status}`:

| Key | Run |
|---|---|
| `base` | the run itself, when it captured any code of its own: a working-tree or local-commits patch, or untracked files alone |
| `parent` / `forked_from` / `rerun_of` | its origins, when indexed |
| `previous` | the latest earlier unarchived run on the same `branch` with the same `command` |
| `best` | the best other run on the primary declared goal (`primary: true` with a goal, else the first exactly named schema metric with one), with the `metric` it is best on; absent without a declared goal |

A run not indexed yet answers `{}`; an unknown run is 404. Both are viewer
reads with a body-digest ETag.

The run page's **Changes** card (`#changes`, below the training curves, in
read-only workspaces too) offers these baselines as a picker. It defaults to
`base` when present, else `previous`, else the first that exists. `base` shows
the `/patch` files and text, or the untracked file list of a run that captured
only untracked files. Beside a text patch it also lists the run's untracked
files (each tagged `untracked`, "+N more" past the 200 listed, or one line
when their tarball cannot be read), noting that they are not in the diff and
that restore or export brings them back. Any other baseline is diffed through
`experiments-diff` (baseline → this run): it shows the top 5 metrics by |Δ|
(goal metrics first, then "+N more"), a *Params changed* block (count + one
row per param), the changed files and the diff behind *Show diff*, with *Open in Compare →*
(`compare-runs?tab=code&sel=<baseline>&sel=<run>`). Without code or
baselines, it shows one line with the reason. The picked baseline is kept in
the page's `?baseline=` param. Its value is a baseline key or any run ref,
and a ref that is not a baseline gets its own `vs <ref>` choice. So
`/ws/<ws>/app/<app>/run/<verstr>?baseline=<ref>#changes` links straight to
a diff against that run.

A failed run's **Error** card uses the failure fields of the run detail:
`stopped at step N[ of M]` (`last_step`), "Since it last worked: @N name →
Changes" (`last_good`; the link is this run's page with
`?baseline=<last_good>#changes`), and under *last output* the
`output_tail` lines (the error's own captured tail when there are none),
scrolled to the end, with *open full output* pointing at the Output card.

### Series for many runs

A comparison chart fetches the same metrics from many runs at once:

```sh
curl -X POST -H "Content-Type: application/json" \
  -d '{"verstrs": ["1.0.0-dev.a", "1.0.0-dev.b"], "keys": ["loss"], "max_points": 500}' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/series"
```

→ `{"series": {verstr: {metric: [{"step", "ts", "value"}]}}, "series_total":
{verstr: {metric: n}}, "step_metrics": {verstr: {metric: x metric}},
"missing": [verstr, ...]}`. At most 200 runs per request; `keys: null` means
every metric; the runs share the 200,000-point cap. It is a read (allowed with
`--read-only`), but as a POST it needs `Content-Type: application/json` and a
same-site `Origin`.

### Zoom and many keys

Both series endpoints take `step_min`/`step_max` (query params on run detail,
body fields on the batch; either may be omitted, neither combines with `x`).
The range is read straight from the metric files: on a compacted `.vmx` that is
the level-of-detail slice covering it, so a zoom into a 1M-step run reads a few
small byte ranges, not the run. The UI refetches on a chart zoom (debounced)
and keeps the coarse series drawn meanwhile.

`GET .../experiments/{verstr}/metric-keys?prefix=&offset=&limit=` →
`{"keys": [{"name", "count"}], "total", "offset", "limit"}` pages a run's
metric names (sorted; `prefix` filters), for runs with thousands of keys; the
run page's key picker uses it.

### Custom x axis

Both series endpoints can key a metric by another metric's value: run detail
takes `?x=epoch`, the batch body `"x": "epoch"` or a per-metric map
`"x": {"val_loss": "epoch"}` (unmapped metrics come back plain). A joined
point is `{"step", "ts", "value", "x"}`, where `x` is the x metric's value at
the same step (for step-less points, the same `log_metrics` call); points
without a finite x are dropped. The join happens before thinning, and
`series_total` counts joined points.

In the dashboard, the run page's training curves and the Compare page's
curves tab share one x axis control: Step (each metric's declared
`step_metric`, else the step), Wall, Relative, or `x = <metric>` for every
chart. `Log y` is an on/off chip; a log axis labels each tick with its own
value (`1e-4`, `0.001`, `10`).

The run page's overlay box takes an fnmatch glob (`cv*.grad_norm_mean`, the
matcher `define_metric` uses) and draws every training metric it matches in
one chart, sorted, at most 20 (`showing 20 of N matches` past that), on the
page's x axis and `Log y`. The step ranges a run marked with
`run.mark_range(name, start_step, end_step)` are shaded as x bands on every
step chart (the overlay too) and named under the toolbar. Run detail carries
them as `ranges: [{name, start_step, end_step}]` (the first 100 distinct, in
log order) and `ranges_total`, both absent when the run marked none.

### Diffs and artifacts

`GET .../experiments-diff?v=&to=` materializes both runs and diffs their code.
Results are cached per pair, at most two diffs run at once (a third waits, then
gets 429), and the text is capped at 2 MB (`truncated: true`). A record with no
base commit (a git-free run) answers `diff: null` with the reason in
`diff_unavailable`.

`metrics_delta` maps each key of the two runs' folded `metrics` whose value
differs to `{from, to, goal, param}` (`from`/`to` are `null` on a run without
the key). `param: true` marks a numeric param folded into `metrics`: every run
holding the key holds it as a param it never logged as a metric (a logged
metric of a param's name keeps its place; rows list such names in
`logged_params`), so a param only one run set is still a param. The Compare *Code* tab and the run page's
*Changes* card list those under *Params changed*, the rest as metrics.
`goal` is one goal for both runs: the app's metrics schema, else the two runs'
own `define_metric` goals, else (store workspaces) the board's goal from the
other runs (none when they disagree). When the two runs declare
different goals the delta has no direction: `goal: null`, `goal_conflict:
true` and `goals: [from's, to's]`, and the web shows *goals differ* instead
of a better/worse tone.

`GET .../experiments/{verstr}/artifacts/{path}` downloads an artifact, and
`.../outputs/{path}` one of vmn's own outputs (`output.log`, media, tables;
`path` may be nested, `a/b/c.txt`; `..`, `.`, empty parts and backslashes are a 400)
from local and remote stores alike; a remote object streams straight through.
Downloads are never gzipped, carry a `Content-Type` guessed from the name, and
an RFC 5987 `filename*`.
A file in a local record dir (a `file://` store or a git workspace) is
served only when it resolves inside that dir: a symlink, or a file under a
symlinked directory, that leads out of the run's record answers 404, the same
as a missing file (the same holds for `.../table/{path}`). Symlinks between
files of one record still work. A store laid out by hand with artifacts
symlinked to another volume no longer serves them through the UI; job-side SDK
reads are unaffected.

### Media

What `run.log_image` / `log_table` / `log_histogram` recorded (see
[sdk.md](sdk.md#tables-images-and-histograms)) shows in the run page's
**Media** section: an image grid with a step slider per key, a table viewer
(key and step pickers, server-side sort, 50 rows a page) and a histogram chart
per key, with an *over time* view stacking every step.

- Images download through the artifact route
  (`.../outputs/media/<name>/<step>.png`, `image/png`).
- `GET .../table/{path}?offset=0&limit=100&sort=<column>&order=asc|desc`
  answers `{"columns": [{"name", "type"}], "rows": [[...]], "total", "offset",
  "truncated"}`. Sorting covers the whole table (missing cells last); `limit`
  is capped at 1000. Unknown path: 404; not a table, or an unknown column: 400.
- `GET .../histograms/{name}` answers `{"name", "steps": [{"step", "bins",
  "counts"}], "total"}`: at most 100 evenly spaced steps, first and last
  included, with an ETag. Names may contain `/` (`gradients/fc.weight`).
  Unknown run or name: 404. Run detail inlines steps only for small runs, so a
  model watched with [`torch_watch.watch`](sdk.md#pytorch--watch) (hundreds of
  keys) does not bloat each poll; the run page fetches the keys it shows.

### Lineage

`GET .../experiments/{verstr}/lineage?depth=1&limit=100` answers the same
object as the SDK's [`get_lineage`](sdk.md#lineage) (`upstream`,
`downstream`, `datasets`, `models`, `truncated`), from the index snapshot.
`depth` is 1..10 and `limit` 1..1000 (else 400); an unknown run is a 404. The
run page shows it as a **lineage** card with a depth picker and badges linking
each used model/dataset version to its registry page.

`GET /workspaces/{ws}/models/{name}/versions/{n}/lineage` is the version side,
[`version_lineage`](sdk.md#lineage): `{model, version, kind, status, producer,
consumers}`. Invalid name: 400; a version that never existed: 404. The model
page shows it with a version picker.

### Similar runs

`GET .../experiments/{verstr}/similar?top=10&all_apps=0&archived=0` answers the
runs most like that run, as [`vmn-exp similar -v`](experiments.md#similar)
ranks them: the run itself, its run tree and its reruns (same code, params
and inputs; forks are kept) are left out, and a sweep or the reruns of one
config show as their best run.
`GET ws/{ws}/apps/{app}/similar?text=...` is the text-only query in one app,
like `vmn-exp similar --context ... --text-only`. With `all_apps=1` either
covers every app of the workspace; `GET /api/v1/similar?text=` covers every
workspace you may view ([server.md](server.md#postgres-and-replicas)).

```sh
curl -G -H "Authorization: Bearer $VMN_UI_TOKEN" \
  --data-urlencode 'text=label smoothing, soft targets' \
  "http://localhost:8265/api/v1/workspaces/my-repo/apps/my_app/similar?top=5"
```

```json
{"items": [{"workspace": "my-repo", "app": "my_app", "verstr": "0.0.3-dev.abc1234.def5678",
            "name": null, "score": 0.82, "reasons": ["shared: label smoothing"],
            "signals": {"text": 0.82}, "group_size": 3,
            "goal": {"metric": "val_loss", "goal": "min", "value": 0.31},
            "author": "alice@x.io", "timestamp": "2026-09-20T10:02:11Z", "status": "succeeded",
            "note": "smoothing 0.1", "intent": {"text": "...", "keywords": ["label smoothing"], "truncated": false}}],
 "truncated": false}
```

- `intent` is the first 2 KB of the run's intent text with its keywords, or
  `null`; `truncated` says more runs matched than `top`.
- Ranked by FTS5 bm25 like the CLI ([how](experiments.md#similar)), never
  from the Postgres search rows (they carry no features or intent). An app
  whose index persists in a SQLite file (a git workspace's
  `<data_dir>/index/`, a store workspace's SQLite cache) is searched in that
  file, which every index save files; any other (a store cached in Postgres,
  `--no-index`) gets a host-local FTS5 database of its own under
  `<data_dir>/index/similar/` (in memory with `--no-index`), kept in step
  with the app's index on every refresh. A
  run's similar runs, in every app searched, are scored under the target app's
  (the run's) conf `experiment.similar.weights`, in git workspaces only (a
  store workspace has no conf); a text query on its text alone. Archived runs
  only with `archived=1`. `q=<query>` narrows the candidates with the
  [query language](sdk.md#the-query-language), like `vmn-exp similar --query`
  (a bad query: 400).
- `{verstr}` is a full verstr (no `latest`/`@N`). `top` is 1..100; a blank
  `text` or one over 4 KB, a bad app or verstr: 400. An unknown run or
  workspace: 404. Viewer role; ETag/304. A request that cannot answer within
  10 s (an app's index or its FTS5 documents still being filled, as after
  an upgrade's re-derive)
  gets a 503 with `Retry-After`; the filling goes on, so the retry is quick.
- The run page shows a **similar runs** card beside lineage (loaded when
  scrolled near, with a *this app* / *all apps* choice): each run's link
  (labelled with its app when it is another), score, status, goal metric,
  author, age, `(+N runs)`, its reasons as chips and its intent, collapsed.
- The leaderboard's query bar has a **similar** toggle inside it: the box text
  then goes to the per-app text route, with every filter token (query, branch,
  status, search) as `q` (and the archived token), and a results card replaces
  the charts and table; leaving the mode restores the typed text and the table.
- The leaderboard has one filter grammar: the query bar shows every filter as a
  removable token worded as its clause (`status = "failed"`, `branch = "main"`,
  `text ~ "batch"` for free text over name/verstr/note/branch, `archived`, and each
  top-level `and` conjunct of the query). The status chips, branch picker and
  archived switch (one toolbar, a single Tab stop; the arrow keys move inside
  it) write tokens; a hand-typed `status = ...`/`status in (...)`/
  `branch = ...` clause becomes the same token (Enter commits the text,
  Backspace in an empty box drops the last token). The URL keeps `q`, `status`,
  `branch`, `search` and `archived`. Typed text that compares a word no field
  matches (`lr=0.1`) searches as text instead of failing on the server, with a
  hint offering `params.lr=0.1` (or `metrics.<k>`) when the app has that key.
- A `?` in the query box (sharing one Tab stop with the similar toggle) opens
  query help: this app's `metrics.<k>`/`params.<k>`/`tags.<k>` fields, the
  main row fields, the operators and three examples built from the app's keys
  and the loaded rows' values; picking one puts it in the box. Escape closes
  it and returns focus to the `?`.
- The run log describes `features` entries as `features: N files, M functions,
  K commits (author)` and intents as `intent: <first line> [keywords]`.

### Model registry API

Under `/api/v1` like the rest (concepts and rules in
[models.md](models.md)):

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/workspaces/{ws}/models[?kind=model\|dataset][&offset=&limit=]` | `{"models": [row...]}`, name-ordered, each row with its `kind`; any other `kind` is a 400; with `offset`/`limit` one page plus `"total"` (after the `kind` filter) |
| `GET` | `/workspaces/{ws}/models/{name}` | `{name, kind, description, versions, aliases, audit}` |
| `GET` | `/workspaces/{ws}/models/{name}/versions/{n}/lineage` | Producer and consumer runs ([Lineage](#lineage)) |
| `POST` | `/workspaces/{ws}/models/{name}/versions` | Register a run-backed version; body `{"run": {"app", "verstr"}, "artifact_path"?, "alias"?, "description"?}` → `201 {"version": N}` |
| `POST` | `/workspaces/{ws}/models/{name}/aliases` | Move an alias; body `{"alias", "version", "expect"?}`; 409 on an `expect` mismatch |
| `DELETE` | `/workspaces/{ws}/models/{name}/aliases/{alias}` | Remove an alias |
| `POST` | `/workspaces/{ws}/models/{name}/versions/{n}/status` | Body `{"status": "active"\|"deprecated"\|"deleted"}`; 400 when deleting a version an alias points at |

The list answers from an in-memory snapshot of the registry, refreshed in
the background (every 30 s, re-reading only the models whose files changed)
and at once after a write through these routes; its first build reads each
model's header, log and latest version concurrently. It and the lineage
routes' registry snapshot share one registry listing per refresh. A version's
`artifact_uri` is its `artifact_path` as is when that is absolute (any
`scheme://` URI or an absolute path), else the path in its run's record.

Registry writes run in-process (no job, no repo lock) and are 403 with
`--read-only`. The TypeScript contract is
`packages/vmn-exp/webui/src/apiModels.ts`.

### Caching and compression

JSON is rendered with `orjson` when installed (the `orjson` extra; else the
standard library; NaN/inf become `null` either way) and
gzipped when the client accepts it. The web bundle (`/assets/*`, `index.html`
and client routes) is served `Cache-Control: no-cache` with ETags, so an
upgrade never serves a stale chunk and a reload revalidates to a bodiless 304.
Library code (React, the router, TanStack) is its own chunk, `vendor.js`,
which changes only with a dependency bump, so after an app upgrade it still
answers 304; `npm run build` fails when the app's entry chunk
(`assets/index.js`) outgrows its budget in `webui/scripts/check-bundle.mjs`.
