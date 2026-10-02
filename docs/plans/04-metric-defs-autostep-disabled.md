# Plan 4 + 7: finish `define_metric`, auto-incrementing step, disabled mode

> **Base: `master`** (re-verified at 0096782, after the `feature-parity` merge and 157d864 code store).
> `SDK=` `packages/vmn-exp-sdk/src/vmn_exp`, `APP=` `packages/vmn-exp/src/vmn_exp`, `WEB=` `packages/vmn-exp/webui/src`.
> `SDK/sdk/run.py` is 603 lines; `class Run(MetricDefinitions, RunArtifacts, RunMedia, RunAlerts)` (`run.py:220`)
> — every new Run method goes in a mixin module.

## Already on master

`run.define_metric(name, step_metric=None, summary=None, goal=None, **fields)` (`SDK/sdk/metric_defs.py:17`, 36 lines),
`define_metric` log entry with fnmatch globs (exact beats glob, `SDK/core/step_metric.py`), fold `extrema` +
`metric_defs` (`SDK/core/fold.py:53-54,163-177`), `SUMMARIES = ("min","max","last")` (`SDK/core/metric_summary.py:26`),
policy order run → conf → `last` at read time (`with_policies`, `metric_summary.py:98`), `metric_summary` in
rows/detail (`WEB/types.ts:29` `MetricSummary`, `WEB/pages/RunSections.tsx:85`), `step_metrics` in `get_run`
(`SDK/sdk/reader.py:242`)/UI, x-metric charts. Tests: `test_metric_summary_fold.py`, `test_metric_summary_index.py`,
`test_metric_summary_sdk_cli.py`, `test_metric_summary_ui.py`, `test_step_metric.py`, `test_ui_step_metric.py`.
`NoOpRun` (`SDK/sdk/ranks.py:45`) already has `define_metric` (via `_ignore`, `ranks.py:91`) and `start_step = None`;
`test_noop_run_exposes_every_public_name_of_a_real_run` (`tests/test_sdk_ranks.py:106`) enforces parity.

**Not implemented anywhere (verified):** `hidden`, `first`/`mean` summaries, cross-run/declared goals, any
`VMN_MODE`/disabled mode, any global step counter (`run.step`), `vmn-exp add --define-metric`.

## Facts

- Fold `_keep_latest` (`SDK/core/fold.py:106`) keeps the greatest `(timestamp, writer, pos)` (`_sort_key`, `fold.py:100`); fold persists in SQLite → any semantic change bumps `SCHEMA_VERSION` (`SDK/core/index_store.py:20`, currently `exp-index-7`). `_refold_merged` (`SDK/core/index_logs.py:89`) folds writers in sorted-id order, not by time.
- Schema loading: `SDK/sdk/reader._metrics_schema` (`reader.py:83`), `APP/ui/schema_cache.py` + `APP/ui/experiment_source.metrics_schema` (`:88`), `APP/ui/readers/experiments.metrics_schema` (`:26`), CLI `APP/cli/views.metrics_schema(vcs)` (`views.py:22`, used by `cli/experiment.py:608,714,908`) — **store workspaces get `{}`** (`APP/ui/server.py:220-222` `_app_schema`; also what `/metrics-schema` returns, `server.py:329-332`), so log-borne declarations are their only source of goals.
- Direction comes only from conf by exact name, in **two** places: `SDK/core/log.sort_by_metric` (`log.py:166`, used by `reader.py:165`, `APP/cli/experiment.py:630`, `APP/ui/readers/experiments.py:102`) and `APP/ui/leaderboard_live.py:212` (the UI's cached list sort). Globs and run-declared goals affect neither.
- **Existing bug (out of scope, note it):** `metric_sort_descending` (`SDK/core/log.py:81-94`) returns True for a schema metric without `goal` (its docstring even says "default to higher-is-better"), contradicting `docs/experiments.md:1039` ("no declared goal in the schema sorts as a plain ascending").
- System metrics sampler: `sysmetrics.Sampler(self.log_metrics, system_metrics)` (`SDK/sdk/run.py:280`), ticked from the heartbeat thread in `_beat` (`run.py:513`); records via `self._record(values)` (`SDK/sdk/sysmetrics.py:326`), no step. On by default.
- `Run.log_metrics` (`run.py:420-424`) sets `step` only when given; `_append` (`run.py:499`) runs `sanitize_entry` and may drop the whole entry. No counter exists.
- Explicit steps today: autolog series `0..n` (`SDK/sdk/autolog.py:316`) but final metrics step-less (`autolog.py:297`), Keras `epoch`, HF `global_step` (`SDK/integrations/hf.py:119`), Optuna/Ray explicit (`integrations/ray_tune.py:167`); metrics-file `_parse_metric_line` (`APP/cli/run.py:60`) accepts optional leading `step=N`.
- Media already auto-steps **per `(kind, name)`**: `_media_step`/`_logged` (`SDK/sdk/run_media.py:102-115`, lazily-created `self._media_steps`), not seeded on resume/fork.
- Step-less points chart at relative seconds (`WEB/util/chartData.ts:45-53`, `xOf`); `step_metric._join_key` (`SDK/core/step_metric.py:89-91`) falls back to `("ts", ts)`.
- Rewind (`SDK/core/rewind.py`) only hides entries that have a step (`is_rewound`, `rewind.py:36-47`; `drop_rewound` `:50`).
- Fork/rewind already produce `run.start_step` via `core/fork.next_step` (`SDK/core/fork.py:103`): `fork.seed`/`fork.rewind` (`SDK/sdk/fork.py:27-35`), assigned at `run.py:203`. Plain resume leaves it None.
- `start_run` (`run.py:100-209`) order today: rank check → `NoOpRun` (`:163-164`) → `ensure_logger` (`:167`) → `resume.requested_run_id` (`:170`, **pops** `VMN_RESUME_RUN_ID`, `SDK/sdk/resume.py:28-36`) → resume/fork locate → `create_record` (`:184`). Since 157d864 there is no `snapshot=` parameter: every non-resume run goes through `create_record`, which snapshots and writes/reuses a code object (`vmn-code/<app>` pseudo-app, `SDK/core/code_store.py`) in the store.
- `NoOpRun` is never registered → `current_run()` None → autolog records nothing (`autolog.py:252`).
- `APP/cli/plugin.py:226 _exp_run_without_repo(args)` runs before git/lock (registered `plugin.py:339`); its first branch is the `import-mlflow` intercept (`:234`), then `VMN_SNAPSHOT_METADATA` mode — the right hook for disabled `exp run`.

---

## Feature 4 — finish `define_metric`

**API:** `run.define_metric(name, step_metric=None, summary=None, goal=None, hidden=None, **fields)`
- `summary ∈ min|max|last|first|mean` (**add `first`, `mean`**). Reject `"none"` for now (breaks the `metric_parts` invariant; open question).
- `hidden: bool` — display-only (stays in metrics/sort/query; UI hides from default grid/columns). Same key in conf: `experiment.metrics.<name>.hidden`.
- **Cross-run goals:** *effective schema* = conf + run-declared `goal`/`hidden` for names conf doesn't declare, latest run wins. Drives sort direction and UI hidden columns. **Never** passed to `summarized()`/`with_policies` (run A's goal must not change run B's summary).
- Glob goals in sorting: `metric_sort_descending` resolves via `step_metric.lookup`; both sort sites (`log.py:166`, `leaderboard_live.py:212`) switch to `metric_goal`.

**Fold:** repeated metric extrema grows `(min, max)` → `(min, max, sum, n)` (finite only, order-free). `first` must be key-ordered, not arrival-ordered (`_refold_merged` folds writers by id) → `fold["firsts"] = {name: (value, *key)}` for repeated metrics, seeded at bare→repeat transition; helper `track_first` in `metric_summary.py`. `summarize` emits last/min/max/first/mean. **Bump `SCHEMA_VERSION` → `exp-index-8`.**

**Modules**
- 1a core/SDK/CLI: `core/metric_summary.py` (+~45); `core/fold.py` (+~5); **new** `core/metric_schema.py` (~90: `declared_schema`, `effective_schema`, `metric_goal`); `core/log.py` sort via `metric_goal`; `core/index_snapshot.py` (259 lines)/`index.py` (457 lines — keep additions in `index_views.py`/`index_snapshot.py`) sparse `declared_defs` + memoized `snap.declared_schema()`; `sdk/reader.list_runs` (`reader.py:159-165`) sorts with effective schema, summarizes with conf; `sdk/metric_defs.py` `hidden`; **new** `APP/cli/define_metric_args.py` (~70): `vmn-exp add <app> -v <ref> --define-metric NAME [--goal] [--summary] [--step-metric] [--hidden]`.
- 1b UI: server (`ui/server.py` `_app_schema` callers, `ui/leaderboard_live.py`) sorts with effective schema, `/metrics-schema` (`server.py:329`) returns it (store workspaces get declared goals); detail `hidden_metrics`; `WEB/components/TrainingCurves.tsx` collapsed "hidden" section; `WEB/hooks/useLeaderboardColumns.ts` + `APP/ui/leaderboard_columns.py` drop hidden defaults; `MetricSummary` (`WEB/types.ts:29`, `pages/RunSections.tsx:85 summaryLine`) gets first/mean.

**Tests:** `test_mean_summary_ranks_on_the_mean_of_finite_values`, `test_first_summary_is_the_earliest_by_timestamp_across_writers`, `test_first_ignores_a_same_named_param`, `test_metric_summary_payload_has_first_and_mean`, `test_summary_none_is_rejected`, `test_repeated_metric_extra_state_is_bounded`; new `tests/test_metric_schema.py`: `test_conf_goal_beats_declared_goal`, `test_latest_run_declaration_wins`, `test_glob_goal_sets_sort_direction`, `test_declared_goal_sorts_without_conf`, `test_declared_goal_does_not_change_another_runs_summary`; `test_define_metric_hidden_is_recorded`, `test_hidden_must_be_bool`, `test_cli_add_define_metric_appends_entry`, `test_cli_add_define_metric_rejects_bad_summary`; `test_detail_lists_hidden_metrics_from_run_and_conf`, `test_metrics_schema_endpoint_merges_declared_goals_for_s3_workspace`; `test_index_schema_version_bumped_refolds_old_records`; vitest: hidden grid section, hidden not default columns, first/mean shown.

---

## Feature 4b — auto-incrementing step

**Decision:** one global per-run counter with a high-water mark (W&B `_step`).
- No `step` → `step = run.step`, then +1. Explicit `step=s` recorded as given; `run.step = max(run.step, s+1)`.
- Steps below the high-water mark are **kept** (W&B drops them; vmn never loses data, fork/rewind re-log old steps).
- An all-dropped call (after `sanitize_entry`) consumes no step. Thread-safe.
- Per-key counters rejected (breaks shared step in one call, `step_metric` join, sweep median rule).
- `commit=False` (W&B): current step without advancing — include if ≤ ~20 lines.

**Start:** `run.start_step` (fork/rewind, already set at `run.py:203`) → else on resume (`prior_state is not None`) one past the highest visible metrics step (`drop_rewound(storage.load_merged_log(...))`) → else 0. Seed after `run.start_step = start_step`, before `run._open()` (the heartbeat/sampler must not log first).

**Not auto-stepped:** system metrics (`sys_*`: pass a new `self._log_unstepped` to the `Sampler` at `run.py:280` instead of `self.log_metrics`); media keeps its existing per-`(kind, name)` steps (`run_media.py:102-115`); metrics-file protocol unchanged; autolog unchanged (final metrics at `autolog.py:297` now get the next step).

**Modules:** **new** `SDK/sdk/steps.py` (~50, `StepCounter`, `resume_next_step`); **new** `SDK/sdk/run_metrics.py` (~60, `RunMetrics` mixin moving `log_metric(s)` (`run.py:417-424`) out of run.py); `run.py` wiring + seeding; `ranks.py` `NoOpRun.step` + `commit=` on `NoOpRun.log_metric(s)` (`ranks.py:63-67`).

**Tests** (`tests/test_sdk_auto_step.py`): `test_log_metrics_without_step_records_0_1_2`, `test_one_call_shares_one_step_for_all_keys`, `test_explicit_step_raises_the_high_water_mark`, `test_explicit_lower_step_is_kept_and_does_not_rewind_counter`, `test_all_dropped_values_consume_no_step`, `test_commit_false_shares_the_next_committed_step`, `test_system_metrics_carry_no_step_and_consume_none`, `test_concurrent_log_metrics_yield_unique_steps`, `test_resume_continues_after_last_logged_step`, `test_resume_ignores_rewound_steps`, `test_fork_continues_from_start_step`, `test_run_step_property_reports_next_step`, `test_autolog_series_steps_unchanged`, `test_noop_run_step_counts`.

**Compat:** old logs unchanged; mixing old step-less and new stepped runs in an overlay mixes seconds and steps (already true; document). Rewind now hides step-less SDK metrics too (document).

---

## Feature 7 — disabled mode

**API:** `start_run(..., mode=None)` with `None|"enabled"|"disabled"` (else ValueError; no `online`/`offline`). Env `VMN_MODE=disabled`. Precedence: explicit `mode=` > `VMN_MODE` > enabled (mirrors `capture_env`).
- Checked **first** in `start_run` — before the rank check (`run.py:163`), `ensure_logger` (`:167`), `VMN_RESUME_RUN_ID` consumption (`:170`), fork source lookup and `create_record` (`:184`). With `snapshot=False` gone (157d864) `create_record` always snapshots and writes/reuses a `vmn-code/<app>` code object, so the early return is the only way to touch neither git nor the store. Returns `NoOpRun(app_name, disabled=True)`; `Run.disabled = False`, `NoOpRun.disabled` class attr (keeps the parity test green).
- `current_run()` stays None → autolog/integrations take their no-run paths; `VMN_EXPERIMENT_ID` not exported.
- `autolog()` under `VMN_MODE=disabled` patches nothing.
- **`vmn-exp run <app> -- cmd` under `VMN_MODE=disabled`:** intercepted at the top of `_exp_run_without_repo` — no lock, auto-init, snapshot or run_state; env `VMN_METRICS_FILE=os.devnull`, `VMN_MODE` inherited; one stderr notice; `os.execvpe` (child's exit code and signals are its own).
- Other CLI actions ignore `VMN_MODE`.

**Modules:** **new** `SDK/sdk/mode.py` (~40); `start_run` 2-line early return (+ `mode=None` param after `capture_output`); `ranks.py` `disabled`; `autolog.py` guard in `autolog()` (`autolog.py:128`); **new** `APP/cli/run_disabled.py` (~45, injectable `execvpe`), called at the top of `_exp_run_without_repo` (`plugin.py:226`) before the `import-mlflow` branch, only for `action == "run"`.

**Tests** (`tests/test_sdk_disabled_mode.py`): `test_start_run_disabled_returns_noop_and_writes_nothing` (outside any git repo; asserts no run record **and** no `vmn-code/<app>` code object in the store), `test_env_disabled_returns_noop`, `test_explicit_enabled_overrides_env`, `test_invalid_mode_raises`, `test_disabled_run_has_disabled_true_and_id_none`, `test_disabled_does_not_consume_resume_env`, `test_current_run_is_none_under_disabled`, `test_every_run_method_is_a_noop_under_disabled`, `test_autolog_under_env_disabled_patches_nothing`, `test_disabled_on_secondary_rank_also_noop`; `tests/test_exp_run_disabled.py`: `test_exp_run_disabled_execs_command_without_recording`, `test_exp_run_disabled_needs_no_git_repo`, `test_exp_run_disabled_real_child_exit_code`.

---

## Docs

`docs/sdk.md` (summaries first/mean/hidden, cross-run goals, auto-step rules + `run.step` + `commit=`, resume/rewind notes, "Disabled mode"); `docs/experiments.md` (schema `hidden`, glob goals, `add --define-metric`, fix goal-less sort sentence, metrics file stays explicit, `exp run` disabled); `docs/ui.md`; `CLAUDE.md` (`VMN_MODE`, SDK bullet, `exp add` flags).

## Worktrees

| WT | Scope | Depends |
|---|---|---|
| 3 `disabled-mode` | mode.py, start_run, NoOpRun.disabled, autolog, run_disabled.py | — |
| 2 `auto-step` | steps.py, run_metrics.py, wiring, resume seeding, NoOpRun.step | — |
| 1a `define-metric-core` | fold/summary/schema/log/index/reader, `hidden`, CLI, index bump | — |
| 1b `define-metric-ui` | server/detail, webui, bundle | 1a contract |

Merge order 3 → 2 → 1a → 1b. Small overlaps only in `ranks.py`, `run.py`, docs.

## Risks

`first` ordering across writers (test shuffled writer order vs `fold_log`); fold memory at 100k runs (pin with test); effective schema leaking into summaries (guard test); mean with NaN (finite only, `n==0` → last); resume reads the log once (later: `max_step` in the fold); auto-step changes sweep median-rule inputs (re-run sweep tests); `execvpe` POSIX-only (flush notice first); `run.py` at 603 lines — wiring for auto-step must be net-neutral or move code into mixins.

## Open questions

1. Is `summary="none"` needed?
2. Should run-declared `step_metric` flow into the effective schema? (proposed no)
3. Media auto-steps follow global `run.step` instead of the existing per-`(kind, name)` counter? (If kept per-name, should it be seeded on resume/fork like `run.step`? Today it restarts at 0.)
4. Auto-step metrics-file lines without `step=`? (proposed no)
5. `VMN_MODE=disabled`: CI kill-switch that always wins, or loses to explicit `mode="enabled"`? (proposed: loses)
