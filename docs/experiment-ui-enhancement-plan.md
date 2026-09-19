# Plan: Experiment UI Enhancement — MLflow/W&B-Competitive, Built for Scale

## Context

vmn's experiment tracking backend is strong (per-writer JSONL, K8s-scale, S3/NFS, snapshot-based creation), but the UI is minimal compared to MLflow, W&B, Aim, and ClearML. The current UI has a sortable leaderboard with small-multiples line charts, a run detail page with training curves, and a two-run compare page. Users expect more: search/filter, sweep visualizations (parallel coordinates, scatter plots), live updates, smoothing, grouping, and the ability to compare N runs on one chart.

**Goal:** Make the experiment UI ultra-responsive at 5000+ experiments. Compelling enough that users don't need W&B or MLflow. Keep the zero-server, files-on-disk philosophy.

**Current tech stack:** React 18 + TypeScript + Vite + Recharts 2.15. Single `styles.css` (dark theme). 20 source files in `webui/`.

### Current scalability bottlenecks (must fix)

| Layer | Current state | Impact at 5000+ experiments |
|-------|--------------|----------------------------|
| Table rendering | Plain `<table>`, ALL rows in DOM | 5000+ `<tr>` = slow paint, high memory |
| Virtualization | None (no react-window/tanstack) | Missing entirely |
| Backend pagination | Only `last=N` tail slice, no offset/cursor | Full dataset always computed server-side |
| HTTP response | Full JSON array, single bulk fetch | ~2-5MB payload blocks UI |
| Mini-charts (ParamPlots) | Recharts SVG with `dot={{ r: 2.5 }}` per row | 5000 SVG circles per metric chart |
| Training curves | Recharts SVG, no downsampling | Degrades above ~1000-2000 points |
| Request mgmt | No abort, no dedup, no debounce | Stale requests pile up on rapid navigation |
| SQLite cache | Exists but invalidates on any single change | Full re-read of all metadata.yml + log files |

## Phase 0: Scalability Foundation + Housekeeping

Before any feature work. This phase makes the UI capable of handling thousands of experiments.

### 0.1 Add frontend test framework + deps

- `vitest` + `@testing-library/react` + `jsdom` as devDeps (TDD compliance)
- `@tanstack/react-virtual` (row virtualization — 3KB gzipped, zero-config)
- Add `test: { environment: 'jsdom' }` to `vite.config.ts`

### 0.2 Split oversized files

`Leaderboard.tsx` is 445 lines (max 300). Extract:
- `ParamPlots` (lines 14-96) → `components/ParamPlots.tsx`
- `NewExperiment` (lines 98-177) → `components/NewExperiment.tsx`

### 0.3 Virtualized table (critical for scale)

Replace the plain `<table>` in Leaderboard with a virtualized container using `@tanstack/react-virtual`. Only render rows visible in the viewport + overscan buffer. The table header stays fixed; the tbody is a virtual scroller.

- **Modify:** `Leaderboard.tsx` — wrap tbody with `useVirtualizer({ count: rows.length, estimateSize: () => 40, overscan: 20 })`
- **Result:** 5000 rows → ~60 DOM nodes at any time instead of 5000
- **Tests:** renders correct row content for scrolled position, handles empty list, row count matches data

### 0.4 Backend pagination endpoint

Add `offset` + `limit` query params to the experiments list endpoint. Default: `limit=200`, no offset. Frontend fetches page 1 immediately, then background-fetches remaining pages.

- **Modify:** `version_stamp/ui/server.py` `list_experiments()` — accept `offset: int = 0`, `limit: int = 200`; apply after sort
- **Modify:** `version_stamp/ui/readers/experiments.py` `sort_rows()` — return `{ rows, total }` when pagination params present
- **Modify:** `webui/src/api.ts` — new `api.experimentsPaged(ws, app, { sort, offset, limit })` returning `{ rows: ExperimentRow[], total: number }`
- **Tests:** offset=0 limit=10 returns first 10; offset=10 limit=10 returns next 10; total is always full count

### 0.5 Progressive loading in Leaderboard

Fetch first page (200 rows) → render immediately → fetch remaining pages in background → merge into state. User sees data in <500ms even with 5000 experiments.

- **New:** `hooks/useProgressiveLoad.ts` (~60 lines) — fetches page 1, then spawns background fetches for remaining pages using `total` from first response. Merges into a single array. Exposes `{ rows, total, isComplete, progress }`.
- **Modify:** `Leaderboard.tsx` — use `useProgressiveLoad` instead of single fetch. Show progress indicator ("Loading 200/5000...") until complete.
- **Tests:** first page arrives fast, subsequent pages merge without flicker, abort on unmount

### 0.6 Request management utilities

- **New:** `hooks/useFetch.ts` (~50 lines) — wraps fetch with `AbortController` (cancel on unmount/re-fetch), deduplication (same URL within 100ms returns same promise), and error state
- **Modify:** `api.ts` `get<T>()` — accept optional `AbortSignal`
- **Tests:** abort cancels in-flight request, dedup returns same promise for concurrent calls

### 0.7 Chart downsampling for large datasets

- **New:** `util/downsample.ts` (~40 lines) — Largest-Triangle-Three-Buckets (LTTB) algorithm. Takes `points[]` and `maxPoints` (default 500), returns visually representative subset. O(n) single pass.
- **Modify:** `ParamPlots` (extracted component) — remove `dot={{ r: 2.5 }}` (no SVG circles), apply LTTB when points > 500
- **Modify:** `Run.tsx` `chartData` useMemo — apply LTTB per series when series length > 1000
- **Tests:** LTTB preserves min/max/endpoints, output length ≤ maxPoints, passthrough when input ≤ maxPoints

## Phase 1: Table-Stakes (close the gaps users expect)

### 1.1 Search/Filter on Leaderboard

Client-side filter toolbar above the table. Three filter types: text search (note/verstr/branch), metric range (min/max per numeric column), branch dropdown. All filtering runs on the full in-memory dataset (loaded progressively in Phase 0).

- **New:** `components/LeaderboardFilter.tsx` (~120 lines) — filter state, renders toolbar row
- **New:** `hooks/useDebounce.ts` (~15 lines) — generic debounce hook, 200ms default. Used by text search input to avoid filtering on every keystroke (critical at 5000+ rows).
- **Modify:** `Leaderboard.tsx` — insert filter, pipe filtered rows to virtualizer + ParamPlots. Filtering uses `useMemo` over debounced search term.
- **Backend:** None — all data already returned
- **Tests:** text search filters by note, metric range excludes out-of-bound, branch dropdown isolates, debounce delays filter application

### 1.2 Live Auto-Refresh

Poll experiments endpoint when user toggles "Live" button. Backend already reads JSONL fresh per request. Smart polling interval: 3s for Run detail (single experiment, small payload), 5s for Leaderboard (many experiments). Uses the paginated endpoint — only re-fetches page 1 (most recent) during live mode to keep updates snappy at scale.

- **New:** `hooks/usePolling.ts` (~40 lines) — reusable interval hook, accepts interval ms and enabled flag. Aborts in-flight request before starting next poll (via `useFetch` from 0.6).
- **Modify:** `Leaderboard.tsx` — add Live toggle button with pulse dot. Live mode re-fetches page 1 only, merges new rows into existing state.
- **Modify:** `Run.tsx` — same for single-run detail (live training curves)
- **Backend:** None
- **Tests:** callback fires at interval, disabling clears interval, abort prevents stacking

### 1.3 Bar Chart for Final Metrics

Recharts `BarChart` showing one bar per run for a selected metric. Toggle between existing line trend and bar view.

- **New:** `components/MetricBarChart.tsx` (~100 lines) — uses Recharts `BarChart`, `Bar`, goal-aware highlighting
- **Modify:** `Leaderboard.tsx` — view mode toggle: "Trend" | "Bar"
- **Backend:** None
- **Tests:** correct bar count, best bar highlighted, handles empty data

### 1.4 Surface user_meta (pull forward from Phase 4)

`user_meta` is returned by the API but never rendered. Needed now because parallel coordinates (Phase 2) uses it for hyperparameter axes.

- **Modify:** `Leaderboard.tsx` — add optional columns for `user_meta` keys (union across rows)
- **New:** `components/ColumnPicker.tsx` (~80 lines) — dropdown with checkboxes for toggling metric + param columns
- **Modify:** `Run.tsx` — add "Parameters" card in detail grid when user_meta is non-empty
- **Backend:** None
- **Tests:** columns appear when data present, absent when null

## Phase 2: Sweep Visualizations (the differentiator)

### 2.1 Parallel Coordinates Plot

THE sweep visualization. Each vertical axis = a param or metric. Each polyline = a run. Brush on any axis to filter. Recharts doesn't have this — custom SVG. **Canvas fallback for >500 runs** — SVG polylines degrade beyond that; Canvas `strokeStyle` + `beginPath` handles 5000+ lines at 60fps.

- **New:** `components/ParallelCoordinates.tsx` (~280 lines) — dual renderer: SVG for ≤500 rows (crisp, hover-friendly), Canvas for >500 (performant). Inline min/max scaling (no d3 dep). Brush interaction dims out-of-range runs, emits filtered row indices.
- **Modify:** `Leaderboard.tsx` — add "Parallel" view tab, connect brush to table filtering (virtualizer scrolls to match)
- **Backend:** None — uses `ExperimentRow.metrics` + `ExperimentRow.user_meta`
- **Tests:** SVG renders correct axes/polylines, brush filters correctly, handles missing values, canvas path for large dataset

### 2.2 Scatter Plot

Metric vs metric or metric vs param. Each dot = a run. Pick X/Y from dropdowns. Recharts ScatterChart handles 5000 points fine with `dot={false}` + custom `shape` that renders only visible viewport points. For >2000 points, disable hover tooltips (use click instead) to avoid O(n) hit-testing per mouse move.

- **New:** `components/MetricScatter.tsx` (~150 lines) — Recharts `ScatterChart`, axis dropdowns, goal-aware best-dot highlighting, click-to-inspect at scale
- **Modify:** `Leaderboard.tsx` — add "Scatter" view tab
- **Backend:** None
- **Tests:** renders points, skips rows with missing values, dropdown changes update chart

## Phase 3: Advanced Analysis

### 3.1 Smoothing Controls

EMA slider on training curves. Show raw (dotted, 30% opacity) + smoothed (solid) lines.

- **New:** `hooks/useSmoothing.ts` (~40 lines) — EMA computation
- **New:** `components/SmoothingSlider.tsx` (~30 lines) — range input 0.0–0.99
- **Modify:** `Run.tsx` — apply smoothing to each series, render both raw and smoothed
- **Tests:** alpha=0 returns original, alpha=0.9 produces correct EMA, handles edge cases

### 3.2 Flexible X-Axis

Switch training curves between step, wall time, relative time. Backend already returns both `step` and `ts` per SeriesPoint.

- **Modify:** `Run.tsx` — segmented control, modify `chartData` useMemo per mode, adjust tick formatter
- **Tests:** step mode uses step values, relative mode computes seconds, handles null ts

### 3.3 Run Grouping with Aggregation

Group by branch or any `user_meta` key. Show mean +/- std per group. Recharts `BarChart` + `ErrorBar` for whiskers.

- **New:** `components/GroupedMetrics.tsx` (~200 lines) — group-by dropdown, computes stats, renders table + bar chart with error bars
- **Modify:** `Leaderboard.tsx` — add "Grouped" view tab
- **Backend:** None — client-side aggregation
- **Tests:** groups correctly, computes mean/std, handles single-row groups

### 3.4 Multi-Run Training Curve Overlay

Select N runs from leaderboard, overlay their training curves on one chart. Reuses smoothing + x-axis from 3.1/3.2.

- **New:** `pages/Overlay.tsx` (~200 lines) — new route, fetches N experiment details in parallel, one chart per shared metric, one line per run
- **Modify:** `main.tsx` — add route `/ws/:ws/app/:app/overlay`
- **Modify:** `Leaderboard.tsx` — remove 2-run selection cap, add "Overlay curves" button for 2+ selected
- **Backend:** None — fetches individual experiment details
- **Tests:** renders chart per shared metric, one line per run

## Phase 4: Surface Hidden Data

### 4.1 Writer Provenance

Inject `_writer` field into merged log entries so the UI shows which pod/person produced each entry.

- **Modify:** `version_stamp/cli/snapshot.py` `load_merged_log()` — inject `"_writer": writer_id` when reading `log.<id>.jsonl` files
- **Modify:** `Run.tsx` — show writer badge on log timeline entries
- **Backend tests:** merged entries include `_writer`, legacy `log.yml` entries don't

### 4.2 Artifacts Browser

List and download experiment artifact files.

- **Modify:** `version_stamp/ui/readers/experiments.py` — replace `artifacts_dir` path with structured `artifacts` list `[{name, size}]`
- **New endpoint:** `GET /experiments/{verstr}/artifacts/{filename}` — `FileResponse` for download
- **New:** `components/ArtifactsList.tsx` (~60 lines) — file list with download links
- **Modify:** `Run.tsx` — add artifacts card when non-empty

### 4.3 from_snapshot + code_verstr

Minor data surfacing:
- **Modify:** `Run.tsx` — show "from snapshot" badge in metadata, show `code_verstr` when it differs from `verstr`
- **Modify:** `Leaderboard.tsx` — show `code_verstr` below `verstr` in table when they differ

## Execution Order & Parallelism

```
Phase 0: Scalability foundation (sequential — everything else depends on this)
  0.1 Test infra + deps (vitest, @tanstack/react-virtual)
  0.2 Split oversized files
  0.3 Virtualized table        ┐
  0.4 Backend pagination       ├── parallel (independent)
  0.5 Progressive loading      │   (0.5 depends on 0.4)
  0.6 Request management (useFetch) ┤
  0.7 Chart downsampling (LTTB)┘
    │
    ├── 1.1 Filter + debounce ─┐
    ├── 1.2 Live refresh ──────├── Phase 1 (parallel worktrees, independent)
    ├── 1.3 Bar chart ─────────┤
    └── 1.4 user_meta ─────────┘
              │
    ├── 2.1 Parallel coords (SVG/Canvas) ┐── Phase 2 (parallel)
    └── 2.2 Scatter ─────────────────────┘
              │
    ├── 3.1 Smoothing ──────┐
    ├── 3.2 X-axis ─────────├── Phase 3 (3.1-3.3 parallel, then 3.4)
    ├── 3.3 Grouping ───────┘
    └── 3.4 Overlay (depends on 3.1 + 3.2)
              │
    ├── 4.1 Provenance ─────┐
    ├── 4.2 Artifacts ──────├── Phase 4 (parallel, independent)
    └── 4.3 from_snapshot ──┘
```

## New Files Summary

| File | Phase | ~Lines |
|------|-------|--------|
| `hooks/useFetch.ts` | 0.6 | 50 |
| `hooks/useProgressiveLoad.ts` | 0.5 | 60 |
| `hooks/useDebounce.ts` | 1.1 | 15 |
| `hooks/usePolling.ts` | 1.2 | 40 |
| `hooks/useSmoothing.ts` | 3.1 | 40 |
| `util/downsample.ts` | 0.7 | 40 |
| `components/ParamPlots.tsx` | 0.2 | 90 |
| `components/NewExperiment.tsx` | 0.2 | 80 |
| `components/LeaderboardFilter.tsx` | 1.1 | 120 |
| `components/ColumnPicker.tsx` | 1.4 | 80 |
| `components/MetricBarChart.tsx` | 1.3 | 100 |
| `components/ParallelCoordinates.tsx` | 2.1 | 280 |
| `components/MetricScatter.tsx` | 2.2 | 150 |
| `components/GroupedMetrics.tsx` | 3.3 | 200 |
| `components/SmoothingSlider.tsx` | 3.1 | 30 |
| `components/ArtifactsList.tsx` | 4.2 | 60 |
| `pages/Overlay.tsx` | 3.4 | 200 |

## Backend Changes

| File | Phase | Change |
|------|-------|--------|
| `ui/server.py` | 0.4 | Add `offset`/`limit` query params to `list_experiments` |
| `ui/readers/experiments.py` | 0.4 | `sort_rows()` returns `{ rows, total }` with pagination |
| `snapshot.py` `load_merged_log()` | 4.1 | Inject `_writer` field |
| `ui/readers/experiments.py` | 4.2 | `_list_artifacts()` helper |
| `ui/server.py` | 4.2 | Artifact download endpoint |

## What We're NOT Building

- **Parameter importance** — requires training an ML model on params→metric (W&B-level infra, overkill)
- **Drag-and-drop layouts** — W&B-level complexity, not worth it for a CLI-first tool
- **Shareable reports** — requires persistence layer beyond files
- **AI-assisted exploration** — bleeding edge (W&B ARIA), premature

## Performance Targets

| Metric | Target | How to measure |
|--------|--------|----------------|
| First meaningful paint (5000 rows) | <1s | Page 1 (200 rows) renders; progress bar for rest |
| Scroll FPS (5000 rows) | 60fps | Chrome DevTools Performance tab during scroll |
| Filter response (5000 rows) | <100ms perceived | Debounced 200ms, `useMemo` filtering, virtualizer re-renders only visible |
| Parallel coords (5000 lines) | <500ms render | Canvas renderer, no SVG path per line |
| Training curve (10k points) | <200ms render | LTTB downsample to 500 points, `dot={false}`, `isAnimationActive={false}` |
| Live refresh (leaderboard) | No jank | Fetch page 1 only, merge delta into existing rows |

## Verification

After each phase:
1. `cd webui && npm test` — all frontend tests pass
2. `cd .. && python -m pytest tests/test_k8s_experiment.py tests/test_ui_experiment_storage.py` — backend tests pass
3. `vmn ui` — launch dev server, visually verify each feature on the leaderboard with real experiment data
4. **Scale testing**: generate synthetic data (script in `tests/gen_experiments.py`) with 5000 experiments, 20 metrics each, 1000-step training curves. Verify:
   - (a) 0 experiments — empty state renders correctly
   - (b) 1 experiment — all features work at minimum
   - (c) 50 experiments — standard team use case
   - (d) 5000 experiments — scroll, filter, parallel coords, scatter all stay responsive
5. Chrome DevTools Lighthouse audit on the 5000-experiment leaderboard — no performance regression below 80 score
