# 13 — Reports and comments

Status: **design, not started**. Builds on [11-central-server.md](11-central-server.md)
(invariants I1–I8, the change journal, roles). This plan replaces §7.3 there.

Paths are under `packages/`; `W` = `vmn-exp/webui/src`, `U` = `vmn-exp/src/vmn_exp/ui`,
`S` = `vmn-exp-sdk/src/vmn_exp`.

---

## 1. Why

W&B's stickiest feature is the **report**: a write-up with live charts that you send to your
team or your manager as a link. vmn-exp has strong charts, but they only live inside pages,
and their settings are page state that can't be shared beyond a URL. The second gap is
**comments**: today a run has one plain-text `note` field (a single-line input,
`W/components/NoteEditor.tsx`), so a conversation about a run has nowhere to live.

### Goals

1. A report = markdown + **live panels** (curves, leaderboard, scatter, parallel coordinates,
   importance, media, tables, histograms, lineage), opened by a stable link.
2. Panels can be added from where the chart already is: "Add to report" on the leaderboard
   charts, the overlay and run pages.
3. Concurrent editing never loses work: a conflicting save is detected, not overwritten.
4. **Publishing** freezes a revision with its data, so a published report survives pruned
   runs and can be exported as one self-contained HTML file.
5. Threaded comments on runs and on reports, with author identity.

### Non-goals (v1)

- WYSIWYG editing, real-time co-editing, cursors. Markdown source with a live preview only.
- Panels that span workspaces. A report belongs to one workspace; panels may target any app
  in it.
- Notifications for comments and @mentions. Section §9 sketches how they'd reuse alerts.
- Report-level permissions finer than the workspace role.

---

## 2. Invariants (inherited from plan 11, applied here)

| # | Rule | Here |
|---|---|---|
| I1 | Storage is the source of truth | Reports, revisions and comments are records in their own store areas. The server holds nothing about them that isn't rebuildable. |
| I2 | The cache is disposable | The report list and comment counts are cache rows, rebuilt by listing. |
| I4 | Runs are written only by jobs | Reports and comments live in **their own areas**, never inside run records. Commenting on a run doesn't touch the run. |
| — | Journal | Every report and comment write goes through `open_storage`, so it's journaled and appears within a second (plan 11 §5.2). |
| — | No silent overwrite | Revisions are claimed with `create_exclusive`, which is truly atomic on every backend. |

---

## 3. Storage layout

Two new store areas, `reports/` and `comments/` ([14-store-layout.md](14-store-layout.md)).
They copy the model registry's pattern (`S/registry/store.py`): a header record, immutable version
records, and an append-only log folded last-writer-wins.

### 3.1 Reports: area `reports/`

```
reports/<rid>/              one scope per report (a single prefix: delete = one prefix)
  header/                   header record
    metadata.yml            {type: report_header, format_version, created_at, created_by}
    log/<writer>.jsonl      title / archived / pinned / published_rev changes (folded LWW)
  v<N>/                     revision N, immutable, claimed with create_exclusive
    metadata.yml            {type: report_revision, base: N-1, author, created_at, message}
    report.md               the body
    data/<panel-id>.json    published revisions only: each panel's materialized data (§6)
  comments/                 the report's comment thread (§3.2)
```

- `<rid>`: `r` + 12 lowercase base32 characters (random), a valid path component and verstr.
  Reports are found by id. Titles are mutable and not unique.
- **Header log entries** use the registry's entry shape `{type, ts, writer, pos, actor, …}`
  (`S/registry/log.py`), monotonic `ts`, folded on `(ts, writer, pos)`:
  `title`, `archived`, `pinned`, `published` (`{rev}`).
- **A save** = claim `reports/<rid>/v<N+1>` with `create_exclusive`, where N is the revision the
  editor started from. If the name is taken, someone saved first: the server returns
  **409** with the newer revision, and the UI offers a merge (§7.3). Unlike the registry's
  alias `--expect` (read, check, append: advisory), this is atomic, so two racing saves
  can't both win.
- The latest revision is the highest N that exists. Listing names is enough to find it.

### 3.2 Comments: area `comments/` (runs) and `reports/<rid>/comments/`

```
comments/<app-key>/<verstr>/   a run's thread (same scope/name as the run in runs/)
  metadata.yml                 {type: comment_thread, target: {kind: run, app, verstr}}
  log/<writer>.jsonl           comment entries
reports/<rid>/comments/        a report's thread, same files, target {kind: report, rid}
```

- A run's thread has the run's own key, so no name encoding is needed, and the thread of a
  report is deleted with the report's prefix.
- The first comment claims the thread record (`create_exclusive`; losing the race is fine,
  the record exists either way) and appends. Later comments only append.
- Entries:

  ```json
  {"type": "comment", "id": "c<base32>", "ts": "...", "writer": "...", "pos": 3,
   "actor": {...}, "author": {"id": "p_123", "name": "Dana"},
   "text": "markdown subset", "reply_to": null, "anchor": null}
  {"type": "comment_edit", "id": "c…", "text": "..."}
  {"type": "comment_delete", "id": "c…"}
  {"type": "comment_resolve", "id": "c…", "resolved": true}
  ```

  `anchor` (optional) pins a comment to a place: `{panel: "<panel-id>"}` in a report, or
  `{metric: "loss", step: 1200}` on a run.
- Fold: per `id`, last writer wins on `(ts, writer, pos)`; a delete is a tombstone (text
  hidden, the thread structure kept).
- **Author identity:** with a server (plan 11 auth), the principal id and display name.
  Without one, `actor_identity` (writer id + git email + OS user, `S/registry/log.py`).
- **Who may edit or delete:** the author, or an admin. The server enforces it. Without a
  server, anyone who can write the store can append, as with any file. That's stated
  plainly in the docs.
- **Prune:** pruning a run deletes its `comments/<app-key>/<verstr>/` thread (`S/cli/prune.py`).
  Deleting a report deletes its thread.

### 3.3 Format versioning

Both areas' records carry `format_version` (`S/core/record_format.py`). Readers skip newer
formats with a warning, as for runs. The panel spec (§4) has its own `v:` field.

---

## 4. Panel spec

Today no panel spec exists. Each chart keeps its settings in component state (smoothing,
x mode and log scale in `TrainingCurves` and `Overlay`), or in the leaderboard URL
(`hooks/useLeaderboardView.ts`). The closest thing is the `ChartView` enum
(`trend|bar|scatter|parallel|grouped|importance`).

A panel is a fenced block in `report.md`:

````markdown
## Learning-rate sweep

The cosine schedule wins once warmup is ≥ 500 steps.

```vmn-panel
v: 1
id: p7k2
type: curves
app: trainer
runs: {query: 'params.sched = "cosine" and status = succeeded', limit: 20}
keys: [val_loss]
x: {mode: step}            # step | wall | relative | metric (+ metric: tokens_seen)
smoothing: 0.6
log_y: true
```
````

### 4.1 Common fields

| Field | Meaning |
|---|---|
| `v` | spec version (1) |
| `id` | stable id within the report (anchors, comments, published data) |
| `type` | one of §4.2 |
| `app` | app name in the report's workspace |
| `runs` | **either** `{verstrs: [...]}` (pinned runs) **or** `{query, sort, order, limit, archived}`: live, using the query language (`S/core/query.py`) and the leaderboard's `RowsFilter` |
| `title`, `height` | optional display |

### 4.2 Types (v1)

| `type` | Extra fields | Component (today) |
|---|---|---|
| `curves` | `keys`, `x`, `smoothing`, `log_y`, `max_points` | `CurveChart` via the batched `POST .../series` (`W/apiSeries.ts`) |
| `leaderboard` | `columns`, `params` | the leaderboard table, read-only |
| `bar` | `metric` | `MetricBarChart` |
| `scatter` | `x`, `y` (metric or param keys) | `MetricScatter` |
| `parallel` | `columns` | `ParallelCoordinates` |
| `importance` | `metric` | `ParamImportance` (server-computed) |
| `grouped` | `group_by`, `metric` | `GroupedMetrics` |
| `media` | one run (`runs.verstrs` of length 1), `key`, `step` (number or `last`) | `MediaImages` |
| `table` | one run, `path` | `MediaTable` |
| `histogram` | one run, `key` | `RunHistograms` |
| `lineage` | one run, `depth` | `LineageView` (already a pure component) |
| `run` | one run | a compact run card (status, key metrics, params, link) |

### 4.3 Validation

- One schema: `S/core/panel_spec.py`, pure (exp-sdk, so the CLI exporter and the server share
  it). A JSON Schema is generated from it and used by the TypeScript side
  (`W/reports/panelSpec.ts`).
- Unknown `type` or invalid fields: the panel renders an error box with the message. The
  rest of the report still renders, and saving is still allowed (so a newer client's panel
  never blocks an older editor).
- Queries are validated with the existing parser (`QueryError` offsets shown inline).

---

## 5. Making charts embeddable

The panel renderer is a registry `type → component`. Each component needs to work from
props alone:

1. **Lift chart state into props, with defaults.** `TrainingCurves` and `Overlay` keep
   smoothing, x mode, x metric and log scale in `useState`. Make them controlled-or-
   uncontrolled (`value`/`defaultValue` + `onChange`), so pages behave the same and panels
   pass the spec in.
2. **Extract `OverlayChart`** (`W/pages/Overlay.tsx:144`, already a memoised inner component)
   into `W/components/`, and reuse it for `curves` panels.
3. **Row panels reuse `useChartRows`** (`W/hooks/useChartRows.ts`), which already fetches
   `experiments-columns` for a filter, metric columns and param columns.
4. **"Add to report"** on the leaderboard charts (`W/pages/LeaderboardCharts.tsx`), the overlay
   and the run page. It serializes the current view to a panel spec (from `ChartView` and the
   URL state) and appends it to a chosen or new report.

Every panel is lazy-mounted (`W/components/LazyMount.tsx`), so a long report only fetches what's
on screen. Panels share the react-query cache, so two panels on the same runs fetch once.

---

## 6. Live vs published

- **Draft and live:** panels query the current data each time they're viewed. A `query`
  panel picks up new runs; a pinned run that was pruned shows "run pruned" in place of its
  series.
- **Publish** (button, role `editor`): writes revision N+1 with the same body, plus
  `data/<panel-id>.json` for each panel. That's exactly the payload the panel fetched
  (resolved verstrs, rows, downsampled series, media URLs as `vmn://` refs). Then it appends
  `published: {rev}` to the header log.
  - The default view of a report is its **published revision**, when one exists, with a
    banner: "published <date> — view live". Editors see the latest draft.
  - Published panels render from `data/` and never query, so they're stable, fast, and
    survive pruning.
  - Data size: the series are already downsampled (`max_points` per series, default 1000 in
    panels), so a report of 20 curve panels is a few MB at most. Media bytes aren't copied:
    published media panels refer to the artifact by `vmn://`, and if it's pruned they show
    "pruned" like a live panel.
- **Export to HTML:** `vmn-exp report export <rid> [--rev N] -o report.html` (store-only,
  git-free). It needs a published revision, or it publishes into a temporary in-memory one
  first. The output is one file: the rendered markdown, the published data inlined as JSON,
  and a small bundled renderer (uPlot plus the panel components built as a separate Vite
  entry, `W/reports/export.tsx`). Images are inlined as data URIs up to a cap
  (`--max-media-mb`, default 20). It opens offline; it's an artifact you can email.

---

## 7. UI

### 7.1 Routes and pages

- `/ws/:ws/reports`: list (title, author, updated, published?, archived filter). Uses
  `W/routes.tsx`, lazy-loaded like the other pages.
- `/ws/:ws/reports/:rid` (`?rev=N`, `?live=1`): view. Panel anchors `#p-<id>`.
- `/ws/:ws/reports/:rid/edit`: editor.
- The apps page and the run page show "Reports using this app/run" (§8.2).

### 7.2 Rendering

- Add `react-markdown` + `remark-gfm`. **Raw HTML is disabled** (no `rehype-raw`). Links get
  `rel="noopener noreferrer"`. Images may only point at workspace media (`vmn://` refs,
  resolved to the media endpoint). External image URLs render as links, so a report can't
  carry tracking pixels.
- The ` ```vmn-panel ` code-block renderer parses YAML (add `yaml`; small, no deps) and
  mounts the panel.
- Headings get anchors; a table of contents appears for reports with more than 3 headings.

### 7.3 Editor

- Split view: a markdown textarea on the left, the live preview on the right.
- "Insert panel": a dialog that picks a type, app and runs (query input with validation,
  `W/components/QueryInput.tsx`) and keys, then inserts a fenced block. A gear on each
  previewed panel opens the same dialog to edit its block in place.
- Autosave the draft to localStorage every few seconds (key `vmn_report_draft:<ws>/<rid>`).
  An explicit **Save** (Ctrl+S) writes a revision with an optional message.
- **On 409:** show the three versions (base, theirs, yours). Offer an automatic line-based
  three-way merge when the edits don't overlap, otherwise a side-by-side resolve view. The
  merge is client-side (`W/reports/merge.ts`, diff3 over lines; the `diff` package or a
  ~150-line implementation).
- History: a list of revisions (author, time, message) and a diff between any two.

### 7.4 Comments UI

- A run page side panel: the thread, reply, edit, delete, resolve. A "comment here" action
  on a chart point fills `anchor: {metric, step}`.
- Report view: comments per panel (`anchor.panel`) and a general thread at the end.
- Markdown subset in comments (same renderer, no panels, no images).
- Leaderboard: a comment count column, from the index (§8.2), hidden by default.

---

## 8. Server and index

### 8.1 Routes

All under `/api/v1/workspaces/{ws}`. They write storage **directly** (no subprocess jobs),
like `U/routes_models.py`, so they work on git and store workspaces alike. Mutations are
refused under `--read-only` (`_require_rw`), and they need plan 11's `editor` role and the
store `edit` capability.

| Method | Path | Notes |
|---|---|---|
| GET | `/reports?archived=` | list from the index |
| POST | `/reports` | `{title, body}` → claims `<rid>` and `<rid>.v1` |
| GET | `/reports/{rid}` | header fold + latest revision + revision list |
| GET | `/reports/{rid}/revisions/{n}` | one revision (body, metadata, `data/` index) |
| GET | `/reports/{rid}/revisions/{n}/data/{panel}` | published panel data |
| POST | `/reports/{rid}/revisions` | `{base, body, message}` → 201 `{rev}` or **409** `{rev, body, author}` |
| POST | `/reports/{rid}/publish` | `{rev, data: {panel-id: payload}}`; the server validates each payload's shape and size |
| PATCH | `/reports/{rid}` | `{title?, archived?, pinned?}` → header log entries |
| DELETE | `/reports/{rid}` | admin: deletes the header, revisions and comment thread |
| GET | `/comments?target=run:<app>:<verstr>` or `report:<rid>` | the folded thread |
| POST | `/comments` | `{target, text, reply_to?, anchor?}` |
| PATCH / DELETE | `/comments/{target}/{id}` | author or admin |

The publish payload comes from the client, which already has it rendered. The server
doesn't recompute it, but it checks that it's well-formed JSON within a size cap (default
2 MB per panel, 50 MB per revision), and that the verstrs in it exist.

### 8.2 Index

- **Reports:** a small per-workspace index of header folds and latest revision numbers in
  the `CacheStore` kv (plan 11 §4.2), refreshed from the journal like any record
  (`reports` journal entries → re-read that report). It also keeps a reverse map
  `app/verstr → [rid]` from parsed panel specs (pinned verstrs only; query panels map to
  the app), for "Reports using this run".
- **Comment counts:** per run, `{total, unresolved}`, folded from `comments/` threads,
  joined into leaderboard rows as an optional `comments` column (so `comments.unresolved > 0`
  works in queries).

### 8.3 CLI

Store-only, git-free, using the same storage resolution as `vmn-exp model`:
- `vmn-exp report list|show|export|delete`
- `vmn-exp comment <app> -v <ref> "text"` and `vmn-exp comments <app> -v <ref>`

There's no CLI editor: reports are written in the UI, or as a markdown file pushed with
`vmn-exp report put <rid|--new> -f report.md` (handy for agents and CI: "write a report of
this sweep").

---

## 9. Later (not in this plan)

- **@mentions and notifications:** parse `@name` in comments; deliver through the alert
  sinks (`S/core/alerts/`: webhook, Slack, command) with a new trigger `comment`.
- **Shared saved views:** today they're in localStorage (`vmn_views:<ws>/<app>`,
  `W/util/savedViews.ts`). The same storage pattern (a `views/` area, one record per saved view)
  would make them shareable.
- **Report templates** (e.g. "sweep summary" generated from a sweep spec).
- **Embedding** a single panel in other tools via an iframe URL `/embed/<ws>/<rid>/<panel>`.

---

## 10. Implementation plan

TDD per CLAUDE.md. Python tests in `packages/vmn-exp/tests/` (template:
`test_ui_models_api.py`, with `WorkspaceManager.attach_path` plus `TestClient(create_app(…))`).
Webui tests with vitest in `__tests__/` next to the code (`renderWithClient`, `fakeUPlot`).

### Phase 1 — storage and API (Python)

| Worktree | Tests first | Code |
|---|---|---|
| 1a reports store | create claims header + v1; save with stale base → conflict carrying the newer revision; two racing saves (threads) → exactly one wins on local and S3 (MinIO); header fold LWW; `reports/` and `comments/` areas on every backend | `S/reports/store.py`, `S/reports/log.py` |
| 1b comments store | thread claim race; append/edit/delete/resolve fold; tombstones keep replies; target name encoding round-trips every valid verstr; prune deletes the run's thread | `S/reports/comments.py`, `cli/prune.py` |
| 1c panel spec | each type's valid and invalid examples; unknown type tolerated by the parser; JSON Schema generated and stable | `S/core/panel_spec.py` |
| 1d routes | every route in §8.1: happy path, 409 body, 403 read-only, foreign Origin refused, author-only edit (with plan 11 auth when present; standalone token = admin) | `U/routes_reports.py`, `U/routes_comments.py` |

### Phase 2 — rendering (webui)

| Worktree | Tests first | Code |
|---|---|---|
| 2a markdown | raw HTML is escaped; external images become links; `vmn://` images resolve; headings get anchors | `W/reports/Markdown.tsx` (+ `react-markdown`, `remark-gfm`, `yaml`) |
| 2b panel registry | each type renders from a spec with mocked API data; invalid spec → error box, rest renders; lazy mount fetches only visible panels | `W/reports/Panel.tsx`, `W/reports/panelSpec.ts` |
| 2c controlled charts | `TrainingCurves`/overlay behave as before uncontrolled (existing tests green), and follow props when controlled | lift state; extract `OverlayChart` |
| 2d pages | list, view (published by default, live toggle), revision history and diff | `W/pages/Reports.tsx`, `W/pages/Report.tsx` |

### Phase 3 — editing

| Worktree | Tests first | Code |
|---|---|---|
| 3a editor | insert-panel dialog writes a valid block; gear edits the block in place; draft autosave restores after reload | `W/pages/ReportEdit.tsx`, `W/reports/PanelDialog.tsx` |
| 3b conflicts | non-overlapping edits auto-merge; overlapping edits open the resolve view; resolved save uses the new base | `W/reports/merge.ts` |
| 3c add-to-report | from each `ChartView`, the overlay and the run page, the produced spec renders the same chart (snapshot of props) | buttons + serializers |

### Phase 4 — publish and export

| Worktree | Tests first | Code |
|---|---|---|
| 4a publish | published revision renders with the API mocked to fail (no queries); size caps refused with 413; unknown verstrs refused | publish route + client payload capture |
| 4b export | the exported HTML opens in jsdom with no network and renders every panel type; media inlined up to the cap | `W/reports/export.tsx` (Vite entry), `vmn-exp report export` |

### Phase 5 — comments UI and index

| Worktree | Tests first | Code |
|---|---|---|
| 5a comments UI | thread, reply, edit/delete permissions, anchors on charts and panels | `W/components/Comments.tsx` |
| 5b index | report list and reverse map refreshed from journal entries; comment counts in rows; `comments.unresolved > 0` query | index kv + row join |
| 5c CLI | `report list/show/export/put/delete`, `comment`, `comments` | `vmn_exp/cli/report.py`, `cli/comment.py` |

After each phase: `/simplify`, docs (`docs/vmn-exp/reports.md`, new; `ui.md` API section;
`experiments.md` CLI reference), then the full suites once on master.

---

## 11. Decisions (agreed 2026-10-02)

1. **A report opens on its published revision** when one exists, with a "view live" toggle.
   Editors land on the draft.
2. **Comments work without a server**, with the same storage pattern: the author comes from
   `actor_identity`, and edit/delete rules aren't enforced (anyone who can write the store
   can append). The docs say so.

Still open:
3. **External images in reports.** Blocked by default (tracking pixels). Recommended: keep
   blocked; revisit if asked.
4. **Sharing beyond the workspace** (e.g. a public read-only link). Not in v1; it needs a
   signed-link design in plan 11.
