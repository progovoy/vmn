# Plan 28: training health, progress and regression at a glance (fgm's seed ideas, triaged)

> A client team, fgm ("fastglobalmacro"), runs walk-forward HPO launches on
> Kubernetes into an S3 store: about 20k runs per launch, in a tree four to five
> levels deep (launch → date → study → trial / refit / assembler → pod). They sent
> "vmn-exp seed ideas from fgm: training health, progress and regression at a
> glance". Their summary: vmn-exp 0.1.24 already gives them outer-run rollups,
> failure clusters, `settled`, `stalled`, `under()` and SSE. What they still can't
> see at a glance is whether a walk-forward is **healthy, progressing, and no worse
> than the last good one**. Every model collapse they have had was found offline,
> after the run finished.
>
> They ask for a **Live** view (what is running on the cluster now) and a **Review**
> view (finished launches), both top-down with a **tree** for drilling in. About half
> of their ideas are new defaults and configuration on existing features. The rest are
> about eight generic additions that would help any sweep or fleet user.
>
> This plan transcribes their document so it stands alone (§0-§1), then checks each
> idea against the code (§3-§4), answers their five questions (§5), maps their
> acceptance incidents to the ideas (§6), and gives an order of work (§7). A
> reviewer's notes on their document are folded in where each idea is discussed.
> The ops issues from the same week are listed in Appendix A. Another agent is
> fixing those now, so they are not designed here.
>
> Paths are relative to `packages/vmn-exp/webui/src/` unless they start with
> `packages/`, `ui/` (= `packages/vmn-exp/src/vmn_exp/ui/`), `core/`
> (= `packages/vmn-exp-sdk/src/vmn_exp/core/`), `sdk/`
> (= `packages/vmn-exp-sdk/src/vmn_exp/sdk/`) or `docs/`.

Status: **proposal** (2026-10-28). Nothing built.

Sources:
- fgm's document, as four screenshots. It is pinned to fgm `master` @ `01eab866`
  (2026-10-27), plus two open fgm MRs (!1733, !1734) and vmn-exp 0.1.24.
- A reviewer's notes on it (one screenshot).
- The code at `3d71ee63` (vmn_exp 0.1.24). `master` is one commit ahead
  (`689a37ad`, Appendix A).

Small print in the screenshots is hard to read in places. Where a word is a guess,
it is marked *(unclear)*.

**Naming.** fgm marks run levels with a tag, `tags.kind` (`launch`, `study`,
`trial`, `refit*`, `assembler`, `pod/<script>`, `process`, `cost_report`). This is
unrelated to the built-in row field `kind` (`outer` / `inner` / `single`,
`docs/vmn-exp/ui.md` row fields; `core/query.py:ROW_FIELDS`). This plan always
writes `tags.kind` for theirs.

## 0. Their setup (fgm §1-§2, transcribed)

| Item | Value |
|---|---|
| Store | `s3://mig-central-stav-internal-data/vmn-exp/` (`store.yml` at the root, layout 2). Configured in fgm's `Tracking/core/_config.py` (`EXPERIMENT_BUCKET`, `EXPERIMENT_PREFIX`). |
| App | `fastglobalmacro` (env `VMN_APP_NAME`), so runs are at `runs/fastglobalmacro/<verstr>/` |
| Writers | every k8s pod, built from their image (SDK `start_run`), plus the orchestrators (pre-registration, out-of-pod tags/notes/finish) |
| Heartbeat | SDK default 30 s. fgm never sends heartbeats itself, so a run counts as `stuck` after `max(3×30 s, VMN_EXP_MIN_STALE_SEC=60)` = 90 s |

**How each kind of datum lands** (the "Type" letters are used in §1):

| Type | SDK call fgm makes | Store file under `runs/fastglobalmacro/<verstr>/` | Index row field | Query |
|---|---|---|---|---|
| **M** metric | `run.log_metrics({k: v}, step=…)` | `metrics/<writer>~<owner>.vms` while live → `.vmx` compacted at finish | `metrics[k]` (summary per `define_metric`, default last), `metric_summary[k]` | `metrics.k > 1` (quote names with odd characters) |
| **D** metric declaration | `run.define_metric(name_or_glob, step_metric=…, goal=…)` | `log/<writer>~<owner>.jsonl` (`{"type":"define_metric",…}`) | `step_metrics`, goal and summary | n/a |
| **T** tag | `run.set_tag(k, v)` / `set_tags`; out of pod: `vmn_exp.sdk.manage.set_tags(app, ref=run_id, tags=…)` | `log/*.jsonl` (`{"type":"tags","set":{…}}`) | `tags[k]` (string, last write wins) | `tags.k = "v"` |
| **P** param | `run.log_params({…})`, or `params=` on `create_run` | `log/*.jsonl` `params` / `create` entry | `params[k]` (typed) | `params.k = 3` |
| **N** note | `run.log_note(text)` | `log/*.jsonl` (`{"type":"note","text":…}`) | **not indexed**. Only the create-time `note` is a row field. | **not queryable** (see N7) |
| **F** finish | `run.finish(exit_code, error=…)`; out of pod: reopen by `run_id`, then `finish` | `run_state.yml` (`exit_code`, `finished_at`, `error{…}`) | `status`, `exit_code`, `error_summary`, `failure_sig` | `status = "failed"`, `error_summary ~ "OOM"` |
| **A** artifact / IO | `run.log_dict(obj, name)`, `run.log_input(uri, name=…)` | `artifacts/<name>`; inputs in `log/*.jsonl` | `outputs`, `inputs` | `inputs."x".uri` |

Outside vmn-exp, on S3 only:
- run-id maps `…/DistributedTrials/<study_id>/vmn_*_run*.json`, which tell pods which
  pre-registered run to open;
- pod logs `…/DistributedTrials/logs/<host>.log` (pointed to by the `log_uri` tag);
- resource-profile JSONs `…/DistributedTrials/profiles/resources/<YYYYMMDD>/<kind>/<pod>.json`;
- pyprind profiles *(unclear)*;
- the offline NN analysis CSVs in which the collapses were found.

**Run tree:**

| Level | `tags.kind` / name | Created by (fgm → SDK) | Parent | Key params | Closed by |
|---|---|---|---|---|---|
| Launch (walk-forward driver) | `launch`; tag `mode` | `tracked_scope("launch")` → `start_run(app, name, tags=…)` | none | | driver, `finish` |
| Date | readable name | `registry.create_run(…, parent=launch, params=…)` → SDK `create_run`; the driver then opens it by id | launch | `trade_date`, `model_type`, `table_name` | driver |
| Study (one HPO per date × target × group) | `study` | `registry.open_study_run` → `create_run(app, name, parent, params=…)` | date | `n_trials`, `model_type`, `table_name`, `target`, `group`, `trade_date`, `seed.key` | orchestrator at close |
| Trial | `trial` | **bulk pre-registration** (`waiting`): `vmn_exp.core.writer.claim_record` + `append_to_log` + private `core.from_snapshot._record_template` (fgm `Tracking/runs/registry.py`). The pod opens it with `start_run(app, run_id=…)`. | study | sampled HPs, `trial_id` | pod; poller on final failure |
| Refit / refit_single / refit_expansion | `refit*` | pre-registered the same way | study | | pod / poller |
| Assembler / regime_assembler | `assembler` | `create_run(…, parent=study)` | study | | pod / poller |
| Pod / process | `pod/<script>`, `process` | `start_run(…, parent=$FGM_VMN_PARENT_RUN_ID)` | any | | atexit, real exit code |
| Cost report | `cost_report`, name `cost_report/<launch_id>` | `create_run(…, parent=launch)` | launch | | cost tool |

Because of pre-registration, **queue time = `started_at - created_at`** can already be
derived for trial, refit and assembler runs. Retries reopen the same run
(`start_run(run_id=…)`). On SIGTERM, a pod **hands its run back** to the
orchestrator: it stops the heartbeat via the private `run._heartbeat` / `_log_sync`
and unregisters from `vmn_exp.sdk.context`. Trial, refit and assembler runs carry
`study_id` but **not** `trade_date` / `group` / `target`; those are params on the
ancestor study.

## 1. The signals they publish (fgm §3, condensed)

"Level" is `tags.kind`. fgm source paths are omitted.

**3a. Is it progressing?**
- `wf.dates_done`, `wf.dates_failed`, `wf.dates_total`, `progress`, `progress_total`
  (M, launch). Dates finished out of planned; a flat line means stalled. **This is the
  real denominator**: inner-run counts grow as dates get planned.
- `study.trials_done`, `study.trials_failed`, `progress`, `progress_total`,
  `study.best_so_far` (only when it improves) (M, step = trials_done, study). Live HPO
  progress.

**3b. Is training collapsing? (model quality)**
- `health.loss_diverge_rel`, `health.gnorm_spike_frac`, `health.gcos_negative_frac`,
  `health.share_top5_mean`, `health.effdim_final`, `health.dead_units_final` (M, step =
  member index; trial, refit_single). Per trained member. Flags: loss_diverge_rel > 1.0
  · gnorm_spike_frac > 0.2 (share of epochs with grad norm > 5× median) ·
  gcos_negative_frac > 0.5 · dead_units_final > 0.7 · loss NaN. Needs ≥ 4 epochs.
- `health` = ok / warn / unstable (T; trial, refit_single). The worst member wins, and
  it only ever escalates: ok = 0 flags, warn = 1 flag, unstable = NaN, ≥ 2 flags, or a
  partial collapse.
- `[member i] warn/unstable: <flags>` · `partial collapse: n/N targets degenerate` (N).
- `state` = nonfinite / collapsed / degenerate, plus a note `quality state: <state>`
  (T + N; trial / assembler / refit_single). nonfinite: CV score NaN/inf. collapsed:
  `nn.g_out ≤ 0.05`. degenerate: every member `yhat_std < 1e-10`. Set out of pod via
  `manage.set_tags`.
- `nn.g_out` (M, no step; assembler and legacy combined `refit`). Output-layer gain,
  **first manifold member only**. A fully collapsed SWA member reads exactly 1/21 (100
  epochs) or 1/17 (80 epochs).
- (!1733) `nn.g_out_member` (step = member), `nn.g_out_min`, `nn.collapsed_members`,
  `nn.collapsed_frac` (M). Every member; catches partial collapse.
- `cv{k}.train_loss`, `cv{k}.grad_norm_mean`, `cv{k}.gradient_cosine_similarity`,
  `cv{k}.share_top5`, `cv{k}.effective_dim`,
  `cv{k}.<layer>_{norm,eff_step,dead_units,spectral_entropy}`, … (regime models
  `cv{k}h.` / `cv{k}l.`) (M, step = epoch; D `define_metric("cv{k}.*",
  step_metric="epoch")`; trial). Per epoch × CV fold. **Collapse signature:** layer
  norms → 0, grad norm → 1e-5, cosine ±1, share_top5 → 1, loss back to ~0, inside the
  SWA window (the last `max(2, 0.2·epochs)` epochs). Healthy runs peak at a grad norm
  of ~2-3.
- (!1733) refit_single per-member prefixes `{target}.d{dup}.<key>` (M). Before !1733
  all members streamed unprefixed keys into one run, so the curves mixed members.
- `<prefix>.<dataset>.<metric>` (M, step = boosting round; trial / refit (GBM)).
  LightGBM training curve.

**3c. Is quality regressing?**
- `value` (D `goal="max"`) and `score` (M, trial). CV objective: mean net Sharpe across
  folds; `value` is the ranked one.
- `n_folds`, `fold_avg.{n_train,n_val,epochs_run,epochs_max,wall_s}` (M, trial). Fold
  shape; `epochs_run < epochs_max` means early stop.
- `best_value` (D `goal="max"`), `best_param_*`, `n_trials` (**P**, study). Final HPO
  result, logged at close. A question for us (§5 Q3).
- `fi.<feature>` (M, assembler / refit). Ensemble feature importance.
- `n_models_fitted` (M, refit_single). Members actually fitted.
- `seed.key` (T; P on study) · `determinism=warn` (T) ·
  `determinism.nondeterministic_ops` (M), note `Non-deterministic op first seen: <op>`
  (study / trial / refit_single). Reproduce a fit exactly; reproducibility risk.
- Like-for-like comparison: same `table_name` + `model_type` + `trade_date` across
  launches.

**3d. Are we losing work?**
- exit code, error (F, all). Errors include `memory ceiling {N}Gi reached`,
  `submission exhausted {N} retries`, `pod died without S3 result (retries
  exhausted)`, `assembler OOM at {N}Gi, cannot escalate`.
- `state` = succeeded / crashed_retrying / crashed_final (T, pod side).
  crashed_final = last attempt.
- `attempt N: <Exc>: <msg>` + traceback + pod log tail (N, crashing run).
- `attempt N: SIGTERM received — run left open for orchestrator` (N, pod run). **The
  only record of an eviction or preemption.**
- `retry attempt N: <reason>`. Reasons: `OOMKilled at XGi`, `pod died without S3
  result`, `GPU->CPU fallback: pods stuck Pending after Ns`, `speculative CPU resubmit
  (straggler)`, `OOMKilled at X -> Y Gi` (N; trial / refit / assembler). **Retries that
  end `done` are invisible except here.**
- `Prep OOM escalation: X -> Y Gi`, `Orch OOM escalation`, `prep failed or timed out`,
  `skipped: models already trained`, `closed by orchestrator at study end`, … (N;
  launch / study / trial). OOM ladder, lost prep, stale skip, orphan repaired.
- `attempt`, `k8s.namespace`, `k8s.job`, `pod.name`, `node.name`, `k8s.label.fgm/kind`,
  `k8s.label.fgm/study_id`, `k8s.annotation.karpenter.sh/do-not-disrupt`, `image`,
  `git_sha`, `cpu.*`, `mem.*` (T, every pod run). Join a run to its pod and node, and
  whether Karpenter may evict it.
- `pod_info.json` (A, every pod run). Full pod identity.
- `log_uri` (T + P, pod runs). The S3 pod log.

**3e. Is it slow? What does it cost?**
- `created_at` / `started_at` / `finished_at` (SDK, all). Queue time and run time.
- `peak_rss_mb` (M, trial). Process RSS high-water mark.
- (!1734) `res.wall_s`, `res.cpu_s`, `res.cpu_util`, `res.mem_peak_mb`,
  `res.mem_headroom` (M, every pod run). cgroup peaks; `mem_headroom = 1 - peak/limit`,
  which goes **negative** when the pod exceeded its request.
- `total_cost_usd`, `stage_<stage>_cost_usd` (!1734 adds
  `stage_<stage>_<field>`, `waste_<bucket>_usd`) (M, cost_report). Kubecost totals per
  launch. **Ignore** `stage_costs_<i>_*`: `<i>` is a cost rank, not a stage, so it isn't
  comparable across runs.
- `coverage` = complete / partial / unknown, `launch_id`, `job_type` (T, cost_report).
  Whether the cost data is complete.
- `REPORT.md`, `summary.json`, `right_sizing.csv`, … (A via `log_input`, cost_report).
  The full report on S3.

**Their caveats (§9), which bind any chart we build:**
- Per-epoch curves are trustworthy only on **trial** runs (`cv{k}.`). On refit_single
  runs before !1733 they mix members.
- The `health.*` member order (step) is call order under a thread pool and isn't
  stable across retries. Aggregate it (max/share); don't align by index.
- `nn.g_out` on master is the first member only, so it catches full collapse, not
  partial.
- `stage_costs_<i>_*` is rank-indexed and not comparable across runs.

## 2. What they say already works (fgm §4), and the corrections

They list, so we don't re-ask: the outer-runs board with run bar, `stalled` and ETA;
the outer-run overview (summary tiles, status over time, metric spread, top-10 runs,
top failure clusters); the failures tab (`failure_sig`); Runs tab facets; the grouped
board with aggregates; `settled` = `never_started` / `lost` once an outer run ends;
`under("<verstr>")` subtree queries; `define_metric` goal/summary/hidden/step_metric;
SSE `…/events`; the `experiments-status` attention strip; `vmn-panel` reports.

The reviewer's corrections, each checked against the code:

| Claim | Verified |
|---|---|
| `kind` clashes with the built-in row field. | Yes: `core/query.py:ROW_FIELDS` has `kind` (outer/inner/single). This plan writes `tags.kind`. |
| Subtree rollups already exist: `tree_status`, `depth`, `children` are queryable, and every row's pill shows its subtree rollup. | Yes. Also, the full rollup (`GET …/experiments/{v}/summary`, `ui/job_rollup*.py`) is answered for **any** run with children, at any depth: a date or a study has one too. Only the Jobs view (`top=`) is limited to depth 0 (`ui/leaderboard_scope.py:is_top`). So N6 is "show 4-5 levels with per-node rollup columns", not a new rollup engine. The `/tree` endpoint (`ui/routes_tree.py`) is the git version DAG, unrelated to runs. |
| A Prometheus endpoint already exists, with `vmn_cache_drift_total` only. | Yes: `ui/routes_cache.py`, `GET /metrics` (viewer role). So Tier 2's feed is "add rollup gauges to `/metrics`". |
| The 90 s stuck window needs both the heartbeat and `run_state.yml`'s `LastModified` to be stale. | Yes: `core/status.py:_liveness_age_sec` takes the fresher of the writer's heartbeat and the store's write time. |
| P1 is a real gap: the strip is hard-coded to stuck + failed in 24 h. | Yes, and narrower than that: `util/attention.ts:attentionParts` shows stuck, failed-in-24h and running. `components/AttentionStrip.tsx` is mounted only on All runs (`pages/Experiments/AllRunsView.tsx`), not on the Jobs view or an outer run's page. |

## 3. Findings from the code that cut across the ideas

**F1. A store workspace reads no `conf.yml`.** fgm's server serves an S3 store, not a
checkout. In a store workspace:
- the metrics schema from conf is `{}` (`ui/server.py:358`);
- `experiment.ui.group_aggregate` falls back to the mean, and `stale_after_min` to its
  default (`ui/experiment_source.py:247-256`).

Only run-declared `define_metric` goals and hidden flags reach the board
(`core/metric_schema.py`). So every "configure it per app in conf.yml" idea (P1, P3,
P4, part of N3) does **not reach fgm today**, whatever keys we add. That is item A0.

**F2. Rollups count every level together.** A launch's `total`, `done`, run bar and
duration sketch add up dates, studies, trials, refits, assemblers, pods and the cost
report alike (`ui/job_tally.py`, `ui/job_rollup.py`). `expected` is `sweep_planned`,
else `params.expected_pods`, else the runs so far
(`ui/job_rollup_payload.py:_expected`). That is why P2 and P3 matter.

**F3. The query language has no relative time.**
- `timestamp` is the creation time (fgm's `created_at`). `started_at`, `finished_at`,
  `duration_sec` and `stale_sec` exist.
- There is no "now minus 1 h", no queue-time field, and `resume_count` (in
  `run_state.yml`, `sdk/resume.py`) is not a row field.
- Time-relative row fields (`stale_sec`, `duration_sec`) are refreshed only for live
  rows (`ui/leaderboard_cache.py` header). A "waiting for 1 h" field on created rows
  would go stale, so relative time must be evaluated at query time (P1).

**F4. The board sorts by dates, `idx`, metrics and `job:*` only**
(`ui/leaderboard_live.py:order_key`). It can't sort by `duration_sec`, a tag or a
param. Tags show as one `c:tags` column, not a column per key
(`pages/leaderboardColumns.ts`).

**F5. The primary metric comes only from conf** (`core/log.py:primary_metric`;
run-declared definitions carry `goal`/`hidden` only). In a store workspace there is no
primary. A rollup's main metric is then the alphabetically first exact goal metric
(`ui/job_tally.py:RollupSpec`). For fgm that is `best_value` before `value`.

**F6. Group by offers a param only with ≤ 20 distinct values** (`util/groupBy.ts:
MAX_PARAM_VALUES`, `ui/facet_values.py:DISTINCT_CAP`). A launch's ~60 `trade_date`
values fall off the menu. `?group=params.trade_date` in the URL still works.

**F7. fgm depends on private API**: `core.writer.claim_record` (public in name but
documented for importers), `core.from_snapshot._record_template`, `run._heartbeat`,
`run._log_sync` and `sdk.context`. vmn-exp shipped 0.1.22 → 0.1.24 in two days. An
API that can break silently is the most likely way fgm gets hurt (reviewer). Items
API1-API3 replace all of it.

## 4. The ideas

Sizes: **S** ≤ about a day and one worktree; **M** a few days, 2-3 worktrees; **L** a
week or more. Each unit is test-first, as usual.

### 4.1 New prerequisites (not in their list)

#### API1. Public bulk pre-registration: `create_runs` (their Q1)

- **Today.**
  - `vmn_exp.sdk.create_run(app, name=, params=, note=, parent=, storage=,
    capture_env=, run_id=)` (`sdk/create.py:43`) registers one `created` (waiting) run.
  - Each call resolves the parent (a storage read), captures the environment (a `pip`
    inspection) unless `capture_env=False`, re-reads the export's features, takes the
    `VMN_EXPERIMENT_DIR` lock in git-free mode, and lists the code version's run names
    unless `run_id=` is given.
  - It takes no `tags=`.
  - That is why fgm went to `claim_record` + `_record_template` + `append_to_log`.
- **Design.** `vmn_exp.sdk.create_runs(app_name=None, runs=[{name, params, tags,
  note, run_id}], *, parent=None, storage=None, capture_env=False, workers=16) ->
  [verstr]`.
  - Shared work once per batch: the snapshot or checkout identity, the features entry,
    the parent resolution and the env (off by default for a batch).
  - Each run is one `create_exclusive` with its create entry (params **and** tags in
    the same write: the fold already applies tags from a `create` entry,
    `core/fold.py:_apply`), plus the parent's child marker. Claims run on a bounded
    pool.
  - With `run_id=` a taken name raises `RunExistsError` per item; `exist_ok=True`
    returns the existing verstr when its parent and name match (idempotent
    re-registration after an orchestrator restart).
  - `create_run` becomes `create_runs` of one, and gains `tags=`.
  - Once fgm is on `create_runs`, rename `claim_record` to `_claim_record` (importers
    only). `_record_template` stays private.
- **Size:** M. **Depends:** none. Bench: 5,000 runs into the fake S3
  (`uiload/s3bench_fast`) at ≥ 200 runs/s.

#### API2. Hand a run back: `run.release()` and `start_run(on_sigterm="release")` (their Q2)

- **Today.**
  - The SDK's SIGTERM handler finalizes every open run as failed: exit 143,
    `signal: SIGTERM`, `received_signal` (`sdk/signals.py`,
    `sdk/run.py:_finalize_signaled`).
  - There is no public way to stop recording and leave the run for another attempt.
    fgm stops `run._heartbeat` / `_log_sync` by hand and unregisters from
    `sdk.context`, so the run reads `running` until it goes `stuck` 90 s later.
  - The only record of the eviction is a note.
- **Design.**
  - `run.release(reason=None)`: drain media uploads, flush the log buffer, stop the
    heartbeat and sampler, and run the final sync within the final-upload deadline.
  - It then writes `run_state.yml` with `state: released`, no exit code,
    `released_at`, `end_reason: released`, and `signal` when a signal caused it.
  - It unregisters from the context, and atexit leaves the run alone.
  - `derive_status` already reads any non-`running` state without an exit code as
    `created`, so a released run is **waiting** again, which is true. No new D12
    status.
  - `start_run(run_id=…)` reopens it. `resume_count` counts the attempts.
  - `start_run(on_sigterm="finish"|"release")`, default `finish` (today's behaviour);
    `release` makes the SIGTERM handler release instead of fail.
  - `core/settle.py`: a released run under an ended parent settles as `lost`, not
    `never_started` (it ran and never finished).
  - New row fields: `resume_count` and `released_at`. `signal` and `end_reason` are
    already row fields, so `signal = "SIGTERM"`, `end_reason = "released"` and
    `resume_count > 0 and status = "succeeded"` (retries that end done) all become
    queries.
  - The job timeline (`ui/job_timeline.py`, per minute: started/succeeded/failed)
    gains `released`. An eviction wave becomes a spike on the outer run's "status over
    time" chart **without indexing notes** (see N7).
- **Size:** M. **Depends:** none.

#### API3. Out-of-pod finish and notes

- **Today.** `vmn_exp.sdk.manage` has `archive_run`, `unarchive_run` and `set_tags`.
  To finish a run from the orchestrator (a poller on final failure, "closed by
  orchestrator at study end"), fgm reopens it with `start_run(run_id)`, which starts a
  heartbeat and marks it running first. Out-of-pod notes need the same.
- **Design.**
  - `manage.finish_run(app, ref, exit_code, error=None, end_reason=None,
    force=False)` writes the final `run_state.yml` directly. It is refused while the
    run is live elsewhere (a fresh heartbeat by both clocks) unless `force`.
  - `manage.log_note(app, ref, text)` and `manage.log_metrics(app, ref, {…})` append
    under the caller's own stream (`core/writer.py:own_stream`).
  - CLI: `vmn-exp add <app> -v <ref> --finish <code> [--error <text>]`.
- **Size:** S. **Depends:** none.

#### A0. App settings a store workspace reads

- **Today.** See F1. A checkout's `conf.yml` `experiment:` block is the only source of
  metric goals, `primary`, `hidden`, summaries and `experiment.ui.*`. A store-only
  server sees none of it.
- **Design.**
  - A store-side settings file per app, `settings/<app-key>/experiment.yml`, in a new
    store area `settings/` (`storage/areas.py`). It holds the same keys as conf's
    `experiment:` that readers use: `metrics.<name|glob>.{goal,summary,hidden,primary,
    step_metric}` and `ui.*` (the new keys below).
  - CLI `vmn-exp settings <app> show|set -f <file> [--store]`. A server editor edits
    it through the UI's admin page, written with the server's edits access like
    reports and comments.
  - Journaled, so servers see a change within seconds.
  - Precedence: checkout conf (git workspace) > store settings > run declarations.
  - CLI and SDK readers in store mode read it too (`list_runs` sort, `vmn-exp list`).
- **Alternative:** a per-workspace `apps:` block in `server.yml`. It is smaller (S), but
  only the server sees it and it is not in the store. Decision D1.
- **Size:** M. **Depends:** none. **Unblocks:** P1, P3/P4 defaults, the N3 match keys
  and N8 hints in store workspaces. Also `primary` (F5).

### 4.2 Tier 0: defaults and configuration on existing features

| # | Their idea | View | Catches |
|---|---|---|---|
| P1 | Attention strip with per-app **configurable queries** in conf.yml, e.g. `tags.health = "unstable"`, `tags.state in (collapsed, degenerate, nonfinite)`, `status = "created" and age > 1h` | Live | collapse while running; the 2026-10-24 1.5-2 h `start_run` hang |
| P2 | Run bar uses a **declared progress metric** (`progress` / `progress_total`) when the outer run logs one; inner-run counts go secondary | Live | stalls; a misleading `1,412/2,000` while dates are still being planned |
| P3 | Overview summary tiles and p50/p90 duration **split by `tags.kind`** (a configurable tag) | both | a refit backlog hidden behind thousands of done trials |
| P4 | Saved default columns/grouping per app (show `tags.health`, `tags.state`, `value`; open a launch grouped by `tags.kind`). fgm will mark `cv*` / `health.*` hidden on their side. | both | noise |

#### P1. Configurable attention queries

- **Today.** `experiments-status` returns counts + `failed_recent` + `rollup`
  (`ui/status_summary.py`). The strip's parts are fixed (`util/attention.ts`): stuck,
  failed in 24 h, running. It is shown on All runs only. `vmn-exp watch` alerts on
  `failed`/`stuck` only.
- **Gap.** No per-app queries; the strip is not on the Jobs view or an outer run's
  page; there is no relative time (F3); store workspaces have no conf (F1).
- **Design.**
  - Settings `experiment.ui.attention: [{key, label, query, level: warn|error}]`, at
    most 8. The built-in stuck and failed-in-24h parts stay first.
  - Query language: `ago("1h")` (also `30m`, `2d`) evaluates to the ISO timestamp that
    long before now, so `status = "created" and timestamp < ago("1h")` works.
    Timestamps already compare as strings (the strip's own `finished_at >= "…"`
    clause does).
  - `experiments-status` gains `attention: [{key, label, level, count, q}]` and
    `?scope=<v>` for an outer run's page. Counts come from the board's cached filtered
    orders (`ui/leaderboard_cache.py`).
    - A time-free query moves by deltas and is O(1) per request after its first
      build.
    - An `ago()` query is keyed by the minute, so it is rebuilt at most once a minute
      per app (O(N); at 588k runs this needs a measurement in B0, else a bisect on
      the timestamp order).
  - Per outer run: each time-free attention query is a counter in the rollup `Tally`
    (`ui/job_tally.py`), moved by the same deltas. The Jobs view row's `job` summary
    gains `attention: {key: n}`, and a `job:attention` sort (the worst first) serves
    the Live view's "needs attention first".
  - Web: the strip on the Jobs view, All runs and the outer run's page (scoped). Each
    part links to the board filtered by its query, as today.
  - Later: `vmn-exp watch --attention` sends a transition alert to the existing sinks.
- **Size:** M (server M, web S). **Depends:** A0 for store workspaces (a git workspace
  works with conf alone).

#### P2. A declared progress metric for the run bar

- **Today.** `progress = done / expected` over every run in the subtree (F2).
  `throughput_per_min` comes from completions in the last 10 min; the ETA from that.
- **Design.**
  - If an outer run's own row carries finite metrics `progress` and `progress_total`,
    its rollup uses them: `done`, `expected`, the bar, and an ETA from
    `progress / (now - started_at)` (or the metric's own first/last time when
    `metric_summary` has it).
  - The run counts become the secondary line (`41/60 dates · 1,412 runs · 3 failed`).
  - `run.set_progress(done, total=None, unit=None)` logs the two metrics step-less
    plus a `progress_unit` param. fgm already logs `progress`/`progress_total` on the
    launch and the study.
  - Settings may map other names (`experiment.ui.progress: {done: wf.dates_done, total:
    wf.dates_total, unit: dates}`).
  - Works at any level, so a study's bar reads `trials 50/50` in the tree (N6).
- **Size:** S-M. **Depends:** none (the mapping needs A0).

#### P3. Summary tiles and durations split by a tag

- **Today.** One tally per parent: KPI tiles (done/expected, failed, running, waiting,
  stuck, p50/p90 duration) over the whole subtree.
- **Design.**
  - The rollup keeps one tally per (parent, split value) for one split field
    (`tags.kind` for fgm; any `tags.<k>`/`params.<k>`). At most 12 values, the rest
    under `other`.
  - `GET …/experiments/{v}/summary?split=tags.kind` (default from settings
    `experiment.ui.split_by`) adds `by: {<value>: {counts, done, failed_pct, duration:
    {p50, p90}}}`.
  - The Overview shows a small table under the tiles: `tags.kind | runs | done |
    failed | running | waiting | p50 | p90`, each cell a link with its clause.
  - Memory: plan 23's ≤ 4 KB per job grows with the number of values. B0 measures it
    at fgm's shape.
  - This also gives N4 its sibling medians by value.
- **Size:** M. **Depends:** none (the request param works without A0).

#### P4. Per-app default view, shared

- **Today.**
  - Saved views live in the browser's localStorage per workspace/app
    (`util/savedViews.ts`).
  - Default columns are computed (`pages/defaultColumns.ts`: goal metrics + varying
    params).
  - `define_metric(hidden=True)` (globs too) hides metric columns and curves, and is
    already honoured in store workspaces. fgm's "mark `cv*`/`health.*` hidden" works
    today.
  - There is no column per tag key.
- **Design.**
  - Settings `experiment.ui.views: [{name, page: jobs|runs|job, search}]`: team views
    shown above "my views" in `components/SavedViews.tsx`. One may be `default: true`
    per page, applied when the URL carries no view params.
  - Columns `t:<key>` per tag key (`show=t:health,t:state`).
  - Sort by any row field, `tags.<k>` or `params.<k>`: unit FS below, which N4 needs
    too.
- **Size:** S-M. **Depends:** A0 (store), FS for tag sorting.

### 4.3 Tier 1: generic additions

| # | Their idea | View | Catches |
|---|---|---|---|
| N1 | **Ancestor field references** in query, columns and group-by, e.g. `ancestor.params.trade_date`, `ancestor(kind="study").params.group`. `under()` already walks the chain. | both | every by-date slice; prerequisite for N2-N4 |
| N2 | **Pivot heatmap** (rows = field A, cols = field B, cell = share matching a query, or min/median of a metric), on the outer-run page and as a `vmn-panel` type | Review (+ Live partial) | BCA collapse growing 3 → 39/240 models across dates; BCAFX 10-20/24; FXMacro full collapse at h180-h360 |
| N3 | **Baseline compare** for outer runs: pin or auto-suggest the last ended run with the same chosen params. Show per-key deltas (`best_value`, unstable share, p90 duration, $/date) and a summary chip. | Review (+ Live early chip) | a regression from a code change, caught at date 5 instead of date 60 |
| N4 | **Derived duration columns** (queue, run) plus a z-score against siblings grouped by a field. Sortable and filterable. | both | a ~7 h CPU-starved refit; scheduling hangs |
| N5 | **Run-page overlay**: glob keys (`cv*.grad_norm_mean`), log-y, a shaded step band from an expression (SWA window) | Review | tells real collapse from a noisy `warn` |
| N6 | **Tree view with per-node rollups** (§5 of theirs) | both | a short path from a launch to the bad leaf |
| N7 | **Notes index**: `notes ~ "SIGTERM"` / prefix facets, a time histogram, and notes feeding failure clustering. Today later notes are only in the JSONL log. | Live | the ~1,400-pod Karpenter eviction wave on 2026-10-24; OOM ladders; retries that end `done` |
| N8 | **Per-metric display hint** (e.g. `define_metric(…, x="index")`) so step-as-index metrics render as bars or a table, not curves | Review | `health.*`, `nn.g_out_member` are unreadable as curves |

#### N1. Ancestor field references

- **Today.** `under("<v>")` reads each row's ancestor chain (`core/tree.py:ancestry_of`,
  the `ancestors` query extra). Rows carry `root`, `parent` and `depth`, and no
  ancestor values.
- **Design.**
  - `up.params.<k>` / `up.tags.<k>` is the nearest ancestor that has the key.
    `up(tags.kind = "study").params.<k>` is the nearest ancestor matching one equality.
    This is the reviewer's caution: `ancestor(kind="study")` would mean the built-in
    `kind`.
  - Resolved through the snapshot's parent map in O(depth ≤ 5). Memoized per base,
    and invalidated on a re-link like the tree fields (`ui/leaderboard_tree.py`).
  - Usable in queries, `show=` columns, `group=` and facets.
- **Weight.** Q5's answer (tags stamped on every run at creation) covers fgm's need
  with no vmn change. N1 is then a generality for other users, not a prerequisite.
- **Size:** M. **Depends:** none.

#### N2. Pivot heatmap

- **Today.**
  - Group by one field, with aggregates and per-group clauses
    (`ui/leaderboard_groups.py`, `leaderboard_group_clause.py`).
  - The outer run's Charts tab has a box plot by param (`pages/Job/JobBoxByParam.tsx`).
  - The `grouped` panel type (`group_by`, `metric`) is in `core/panel_spec.py`.
  - Nothing crosses two fields.
- **Design.**
  - `GET …/experiments-pivot?rows=<field>&cols=<field>&cell=share&match=<query>` or
    `cell=agg&metric=<m>&agg=median|min|max|mean`, plus `scope`, `q`, `status`.
  - Fields are any group field (`tags.<k>`, `params.<k>`, `branch`, `status`, `root`,
    and N1's `up.*` once it exists).
  - Body: `{rows: [values], cols: [values], cells: [[{n, value, clause}]]}`, capped at
    200 × 50.
  - Memoized per snapshot. Under a settled outer run (ended, nothing live) the pivot is
    kept until its subtree changes: a per-job change counter the rollup deltas already
    touch. A finished launch's heatmap is built once per process, as both fgm and the
    reviewer ask.
  - Under plan 27's bounded hot set (M3), settled pivots persist in the index SQLite as
    a side table.
  - Web: `components/PivotHeatmap.tsx` on the outer run's Overview, with field pickers
    from facets. Each cell links to the filtered Runs tab.
  - A `pivot` panel type for reports. Across launches it reads rows `trade_date` ×
    cols `root`.
  - The menu's 20-value cap (F6) does not apply to pivots.
- **Size:** M (server) + M (web) + S (panel). **Depends:** fgm tags (Q5) or N1 for
  fields held on ancestors; P1 for the "share unstable" preset.

#### N3. Baseline compare for outer runs

- **Today.**
  - The run page's `baselines` (`ui/readers/baselines.py`): `previous` = the latest
    earlier run on the same branch and command, and `best`.
  - Compare takes outer runs and suggests comparing their best run
    (`pages/Compare/OuterRunNotes.tsx`).
  - Nothing compares two outer runs' rollups, or their children matched by a key.
- **Design.**
  - Baseline choice:
    - settings `experiment.ui.baseline.match: [params.table_name, params.model_type]`
      (URL `?match=` without A0) picks the latest ended top-level outer run with equal
      values;
    - a tag `baseline=true` pins one;
    - `?to=<v>` overrides both.
  - `GET …/experiments/{v}/baseline?to=` returns rollup deltas:
    - each goal metric's best/median;
    - `failed_pct`;
    - each attention count as a share (P1: the unstable share);
    - p90 duration;
    - a declared ratio such as `$ / date` (T2c, or the per-launch metric fgm logs at
      close).
  - Children are matched by a key field (`params.trade_date` on the date level, the
    outer run's direct children). Per pair: the delta of their main metric, in key
    order.
  - The chip: `▼ best_value from 2024-12 (5 of 41 dates worse than the baseline's
    p10)`. It is computed as matched children finish, so it shows early in Live.
  - Web: a Baseline card on the Overview, a chip on the header and on the Jobs view
    row.
- **Size:** L (server M, web M). **Depends:** P1 (unstable share), A0 or URL params,
  and tags or N1 when the match key sits below the direct children.

#### N4. Queue and run time, against siblings (with unit FS, field sort)

- **Today.**
  - `duration_sec` is a row field (shown in the status cell, queryable, not sortable,
    F4). For a resumed run it spans every attempt.
  - Created and started times are on the row (`timestamp`, `started_at`).
  - The rollup has a duration sketch per parent, but over every level (F2).
- **Design.**
  - **FS:** sort by any row field (`duration_sec`, `queue_sec`, `stale_sec`, …),
    `tags.<k>` (string order) and `params.<k>` in `order_key`, cached like metric
    orders.
  - Row field `queue_sec = started_at - timestamp` (static once started).
  - `duration_ratio` = `duration_sec` over the median duration of its siblings with the
    same split value (P3's sketch). For a running run it uses the elapsed time,
    refreshed per bucket like `stale_sec`. The column reads `3.1× siblings`.
  - Durations are skewed, so a ratio to the median is used rather than a z-score. The
    log-space z from the sketch's p10/p90 could come later.
  - Columns `c:queue`, `c:duration`, `c:ratio`. All of them work as queries
    (`duration_ratio > 3`) and in attention (P1).
- **Size:** M (FS S-M + fields S + web S). **Depends:** P3 for split medians (without
  P3 it is siblings of every level).

#### N5. Run-page overlay

- **Today.**
  - The run page draws one chart per metric (`components/TrainingCurves.tsx`), with a
    substring key search, log-y (`hooks/useCurveControls.ts`), a `step_metric` x axis
    and drag-zoom.
  - Compare overlays runs per key. The `curves` panel takes a key list and `log_y`.
- **Design.**
  - An "Overlay" control on the run page: a glob (fnmatch, the matcher
    `define_metric` uses) draws every matching key in one chart (≤ 20 series), with
    log-y.
  - Bands come from logged ranges, not an expression language:
    `run.mark_range(name, start_step, end_step)` (a `range` log entry) is drawn as a
    shaded x band on all of the run's charts. fgm marks the SWA window per fold.
  - `curves` panel `keys` accept globs.
- **Size:** M (web M, SDK S). **Depends:** none.

#### N6. A tree with per-node rollups

- **Today.** See §2's correction. Rollups exist per node. The Jobs view is depth 0
  (`top=`). An outer run's Runs tab is its whole subtree, flat. `vmn-exp list` prints a
  tree.
- **Design.**
  - Server: `experiments?children_of=<v>` (paged, sorted, filtered like the board).
    Each row is a direct child, carrying its `job` summary when it has children (P2
    progress, P1 attention counts, P3 split counts, best) and N4's ratio.
  - Children load lazily on expand. A hint `open: true` marks nodes with attention > 0
    or live runs.
  - Web: `pages/Job/JobTree.tsx`, a virtualized tree table: status/run bar, worst
    attention (health), best metric, duration vs siblings, cost (T2c). Columns per
    `tags.kind` come from settings `experiment.ui.tree_columns: {<value>: [show
    keys]}`.
  - Unhealthy and live nodes open; healthy ones stay folded. A 10k-run launch opens as
    ~10 rows.
  - The same tree opens from a Jobs view row (Live) and is the outer run's default
    Runs tab layout (a flat/tree switch).
- **Size:** L (server S-M, web L). **Depends:** P1, P2, P3 for its columns; N4.

#### N7. Notes as data

- **Today.** `log_note` entries live only in the log (paged on the run page). The row's
  `note` is the record's note, set at create or edited later. The search index
  (`ui/search_index.py`) covers that one. Failure clusters use row fields only
  (`ui/failure_signature.py`).
- **The reviewer's point.** Indexing every note of 588k runs is likely the most
  expensive ask in the document. Disk and memory are the cost, not reads: the fold
  already reads every log entry. Plan 27 budgets ≤ 1.5 KB per run in published parts.
- **What covers their incidents first:**
  - API2 (`signal`, `end_reason = "released"`, `resume_count`, the timeline's
    `released` per minute) covers the eviction wave and retries that end done.
  - Tags (`retry_reason=OOMKilled`, last write wins) plus a `retries` metric cover the
    OOM ladder.
- **Design, if still wanted after that:**
  - Note **signatures**, not text: the fold masks each note like a failure signature
    (numbers, sizes, ids) and keeps `{sig: count, last_at}`, at most 8 per run, in a
    side table (like `intent_of`).
  - Query `notes ~ "sigterm"` matches signatures.
  - Scoped facets list the top 20 signatures.
  - The rollup timeline counts signatures per minute (the histogram).
  - A failed run without `error_summary` clusters by its last note signature.
- **Size:** M-L. **Depends:** API2 first; re-scope after.

#### N8. Per-metric display hint

- **Today.** `define_metric(step_metric, summary, goal, hidden)`. Every series is drawn
  as a line.
- **Design.**
  - `define_metric(name|glob, chart="line"|"bars"|"table")` and conf/settings
    `metrics.<name>.chart`, carried into the effective schema like `hidden`
    (`core/metric_schema.py`).
  - `bars` draws the last value per step as bars sorted by value, not by step. That
    respects §9: member order is not stable, so the step is a label, not an axis.
    Max and the share over a threshold sit beside the bars.
  - `table` lists step → value.
- **Size:** S-M (SDK S, web M). **Depends:** none.

### 4.4 Tier 2

Their words: "rollup counts as a Prometheus/JSON feed, so our Grafana can alert without
anyone watching the UI · flag a child still heart-beating under an ended parent
(`settled` covers the rest) · show a child's metric on its parent row, divided by a
parent metric (cost per date)."

- **T2a. Rollup gauges on `/metrics`.**
  - Today `/metrics` serves `vmn_cache_drift_total` only (`ui/routes_cache.py`).
  - Add, per workspace and app:
    - `vmn_runs{status}`;
    - `vmn_attention{key}` (P1);
    - for live top-level outer runs and those ended in the last N hours,
      `vmn_job_runs{job,status}`, `vmn_job_progress`, `vmn_job_eta_seconds`;
    - `vmn_index_freshness_seconds` (the `freshness.as_of` age).
  - Cardinality is bounded by the live outer runs.
  - **Needs keep-warm first** (Appendix A, item 1): today the refresher stops 60 s
    after the last request, so an unwatched server serves stale numbers.
  - Size S-M.
- **T2b. A child alive under an ended parent.**
  - `core/settle.py` settles only `created` (→ `never_started`) and `stuck` (→ `lost`)
    runs. A `running` run under a closed parent gets nothing.
  - Add `settled = "outlived"`: still counted as running, with a built-in attention
    part.
  - Size S.
- **T2c. A child's metric on the parent row, divided by a parent metric.**
  - P3's split tallies could carry a sum of a metric per split value (e.g.
    `total_cost_usd` over `tags.kind = cost_report`).
  - Dividing by a parent metric is a derived-column expression language. Defer it:
    fgm will log `cost_per_date_usd` at close (their §7), which today's board and
    Compare already show.
  - Size L if built.

### 4.5 Their proposal: Live and Review views with a tree (their §5)

| | Live ("what's on the cluster now") | Review ("is this launch good to ship?") |
|---|---|---|
| Scope | Active outer runs only: not ended, or ended within the last N hours. Tens of launches, at most ~10⁴ runs. | Ended launches, any age (the whole history, growing with every walk-forward) |
| Questions | Progressing? Stalled? Losing pods? Is anything collapsing **so far**? | Collapse by date × group? Better or worse than the baseline launch? $/date? |
| Freshness | SSE push, seconds | Computed once when the outer run ends, since a settled subtree no longer changes, so it can be cached |
| Default sort | Needs attention first | Newest first; baseline pinned |

Their mock-up, as drawn:

```
LIVE                                              ● live · 3 launches
⚠ 1 collapsing · 1 stalled 40m · 212 waiting >1h · SIGTERM 1.4k/70m (unprotected tbatch)
▾ wf_neu_…59b6  ████ 41/60 dates · ETA 3h · ⚠ 12% unstable so far · retries ▁▃▅
  ▸ 2025-05-31   █████ done      ok         best 1.21   2h10m
  ▾ 2025-11-30   ███   3 running ⚠ 2 unst. best 0.88   4h02m (3.1× siblings)
    ▾ study FXMacro-h180   trials 50/50 · refit 1 failed · assembler collapsed (g_out 0.048)
        refit_single t3   ✕ unstable  partial collapse 4/6   7h12m   [curves] [log]
REVIEW  wf_neu_…59b6 vs baseline wf_neu_…41aa (same table/model)
  heatmap trade_date × group: unstable share   │ per-date Δ best_value │ $/date by stage
  2024-06 ░░░ 2024-12 ▒▒▒ 2025-06 ███ …        │ ▁▂▃▅▆ ▼ from 2024-12  │ refit ▲ 2.1×
```

- *The tree:* in both views each row is a node plus the rollup of its subtree (status
  bar, worst health, best metric, duration vs siblings, cost). Columns depend on
  `tags.kind`. Unhealthy and active nodes auto-expand, and healthy ones stay folded,
  so a 10k-run launch opens as ~10 rows. Children load lazily. 0.1.24 nests one level
  (Group by parent) and the Runs tab is flat; their tree is 4-5 levels deep.
- *The heatmap* is the forest view: date × group cuts across the tree, since group
  sits under date. Each cell links to the tree node or the filtered board behind it.
- Every rollup number links to the filtered board behind it, the same contract the
  attention strip already has.

**Verdict.** The framing is good (the reviewer agrees). Build it as two presets of
what exists, not as two new engines:

- **Live** = the Jobs view filtered to `tree_status in ("running", "created",
  "stuck") or finished_at >= ago("6h")`, sorted `job:attention`. It has the P1 strip,
  P2 bars, N6 tree rows, and the SSE it already has (`hooks/useLiveScope.ts`). It
  touches only live outer runs, which is plan 27 M3's hot set: cheap to serve.
- **Review** = the Jobs view filtered to ended runs, newest first, each with its N3
  baseline chip. The outer run's Overview gains the N2 heatmap and the N3 card, both
  cached once settled.
- `view=live|review` presets beside `jobs|singles|all`. The strip parts
  (`212 waiting >1h`, `SIGTERM 1.4k/70m`) are P1 queries and API2's timeline.

Size: S (presets) once P1, P2, N2, N3 and N6 exist.

## 5. Answers to their questions (§7)

Their side, as they listed it: they will mark `cv*` / `health.*` hidden; log
`best_value` as a metric if we prefer; log launch/date rollups at close
(`health.unstable_frac`, `collapsed_count`, `cost_per_date_usd`) so Review works with
today's leaderboard/Compare; export one real launch subtree (including §8's incidents)
as a read-only fixture store we can develop and benchmark against; and test each piece
we ship against §8 and report back.

**Q1. "Bulk pre-registration: we pre-register thousands of runs through
`core.writer.claim_record` + private `core.from_snapshot._record_template`. Is there,
or could there be, a public `create_runs([…])`, so your refactors don't break you?"**

There is a public single-run `vmn_exp.sdk.create_run` (`sdk/create.py:43`). It
registers a waiting run, optionally under an exact `run_id`. But per call it resolves
the parent, captures the environment (unless `capture_env=False`), reads the export's
features, takes a lock, and lists names (without `run_id`). It takes no tags. That is
too slow and too narrow for thousands.

So yes: API1 adds `create_runs([...])` with params and tags in the create entry, and
the shared work done once per batch. It is top priority, with API2 (the reviewer
agrees): today an internal rename in a patch release could break every launch.

**Q2. "Handing a run back on SIGTERM: we stop the private `run._heartbeat` /
`_log_sync` and unregister from `sdk.context`. Would a public `run.relinquish()` make
sense?"**

Yes, as API2 (`run.release(reason=)`; `relinquish` as an alias if they prefer the
name), plus `start_run(on_sigterm="release")`. The run is flushed and synced, then
written as `state: released` without an exit code. It reads as waiting (`created`) at
once instead of `running` → `stuck` 90 s later. `signal`, `end_reason`, `released_at`
and `resume_count` make evictions and retries queryable. That covers most of N7's
incidents without indexing notes.

**Q3. "`best_value` is a param with `define_metric(goal="max")`. Does ranking pick that
up, or should it be a metric?"**

It does pick it up today:
- A finite numeric param is folded into `metrics` (`core/fold.py:233-238`).
- A run-declared goal enters the app's effective schema, latest run wins
  (`core/metric_schema.py`).
- So sorting, `job:best`, rollups and leaderboard default columns rank on
  `metrics.best_value`.

Log it as a metric anyway (the reviewer's draft says the same):
- a numeric param silently replaces a same-named metric in `metrics`;
- it is listed under Params as well;
- a metric is what Compare's metric diff and `metric_summary` are built for.

Two findings for us:
- vmn-exp's own Optuna integration logs `best_value` (and `objective` per trial) as
  **metrics** on the outer run (`packages/vmn-exp-sdk/src/vmn_exp/integrations/
  optuna_study.py:235`), but declares no goal. It should
  `define_metric("best_value"/"objective", goal=<study direction>)`. Size S.
- Without conf (F1, F5) there is no primary metric in a store workspace, so an outer
  run's main metric is `best_value` only because it sorts before `value`. A0 lets them
  set `primary`.

**Q4. "Is our 30 s heartbeat / 90 s stuck window right for long CPU-bound fits on busy
nodes, or should we raise `heartbeat_interval_sec`?"**

The window is right, with the reviewer's nuance: a run is stuck only once **both** the
writer's heartbeat and the store's `LastModified` of `run_state.yml` are 90 s old.

A CPU-bound fit is not at risk:
- The heartbeat is its own daemon thread (`sdk/heartbeat.py`).
- The remote write goes through a coalescing worker, so a slow PUT never delays the
  next beat (`sdk/state_publisher.py`).
- Python hands the GIL over every 5 ms. NumPy, torch and ctypes-based libraries
  (LightGBM) release it.

Only a C extension holding the GIL for 90 s straight, or a pod frozen outright, would
miss beats. cgroup CPU throttling delays a beat by seconds, not minutes.

The real cost is the other direction:
- Per live run, per 30 s: a GET + PUT of `run_state.yml` (each beat reads the stored
  state first, to drop a duplicate attempt).
- A log segment PUT and a metric segment PUT per sync (`sync_interval_sec`, default
  30). `sys_*` metrics sampled on every beat mean there is always a metric segment to
  ship.
- The server also re-lists each live run once per heartbeat interval
  (`core/index_sweep.py:live_relist_sec`).
- At ~10⁴ live runs that is about 1,300 requests/s against the bucket that was
  throttling (Appendix A, item 2).

For runs that last hours, use `heartbeat_interval_sec=120` (stuck after 6 min) and
`sync_interval_sec=120`, or 300. With API2, an evicted pod writes `released` at once,
so the longer window does not delay what matters.

Today the interval is set only by `start_run(heartbeat_interval_sec=)` and `vmn-exp
run --heartbeat-interval`. It is stored per run, so readers always use the run's own
window.

vmn-side follow-ups:
- `VMN_EXP_HEARTBEAT_SEC` / `VMN_EXP_SYNC_SEC` env vars and settings keys, so an image
  can change them without code (S).
- Skip the pre-beat GET when the previous PUT was ours, using a conditional PUT on the
  stored ETag (S-M; halves the state requests).

**Q5. "For N1/N7, would you rather we encode ancestor fields and retry reasons as tags
on every run (we can do that today) than have new index features?"**

Tags, now. Stamp `trade_date`, `group`, `target` (and `tags.kind`) on trial, refit and
assembler runs **in the create entry** (API1's `tags=`, so it costs no extra write).
That unlocks, with no vmn change:
- P3's split and N4's siblings by value;
- most of N2 through the existing Group by (`?group=tags.trade_date`; F6's menu cap
  aside), facets and filter tokens;
- the outer run's Runs tab sliced by date.

Tags are strings, so dates sort correctly only in ISO form. N1 then becomes
nice-to-have, which moves it down the order.

For N7, use API2's native fields (`signal`, `end_reason`, `resume_count`) rather than a
`sigterm=1` tag. Use a tag for the last retry reason (`retry_reason=OOMKilled`) and a
`retries` metric for the count. Indexing every note is the most expensive item in the
document, so it waits until those are in place.

## 6. Their acceptance incidents (§8), mapped

"Each view should make these obvious **without opening a run page**":

| # | Incident | Their expectation | Caught by | Without new vmn work (tags + today) |
|---|---|---|---|---|
| 1 | RegimeNN BCA/BCAFX collapse growing with `trade_date` | N2 heatmap turns red over time; P1 fires live | N2 (`rows=tags.trade_date`, `cols=tags.group`, `cell=share`, `match=tags.health = "unstable"`); P1 (`tags.health = "unstable"`); N3 chip | Runs tab `?group=tags.trade_date` with `q=tags.health = "unstable"`: counts per date as group headers. No live alert. |
| 2 | 2026-10-24 Karpenter wave (~1,400 SIGTERMs in ~70 min, pods without do-not-disrupt) | N7 histogram spike | API2 (`signal = "SIGTERM"`, timeline `released` per minute on Overview); P1 part `end_reason = "released" and released_at >= ago("2h")`; group by `tags.k8s.annotation…` | Nothing: a handed-back run records only a note today. |
| 3 | 2026-10-24 `start_run` hang (1.5-2 h) and 2026-10-17 (990 refits stuck `waiting`, 8 trials orphaned `running`) | P1 waiting > 1 h, N4 queue column, `settled` | P1 `status = "created" and timestamp < ago("1h")`; N4 `queue_sec`; P3 (waiting per `tags.kind`); `settled` once the parent ends; T2b `outlived` for the orphans still beating | Waiting counts in the rollup (not per kind); `settled = "never_started"` only after the study ends. |
| 4 | XS 20241201 refit t17 at ~7 h | N4 z-score | N4 `duration_ratio` with P3's split (refits against refits), sortable via FS; P1 `duration_ratio > 3` | `duration_sec` is queryable but not sortable, and siblings mix levels. |
| 5 | A launch whose per-date `best_value` drops vs the previous launch of the same table | N3 chip ▼ by date ~5 | N3 (`match: [params.table_name, params.model_type]`, children matched on `params.trade_date`) | Compare two date runs by hand. |

Acceptance for this plan: fgm's exported fixture subtree is loaded as a read-only store
(unit B0). Each incident gets a test asserting the payload that makes it visible: the
heatmap cells, the attention count, the timeline spike, the ratio, the chip. A web test
asserts the strip and chip render.

## 7. Recommended order

The reviewer's ranking, if only four: public pre-registration and relinquish APIs, P1,
P2, N3. Then N2 backed by tags; N5, N7 and N8 last; Review heatmaps cached once a
launch settles.

This order agrees, with two changes:
- A0 goes in front of P1, because P1's "per-app queries" cannot reach a store-only
  server otherwise (F1).
- P3 and FS go before N4, because both N4 and the tree need them.

**Phase 0 (fgm, no vmn change):**
- tags `trade_date` / `group` / `target` / `kind` on every run at creation;
- `define_metric("cv*", hidden=True)` and the same for `health.*`;
- `best_value` as a metric with its goal;
- heartbeat and sync at 120 s for long runs;
- export the fixture store.

**Phase 1 (stop the bleeding, then Live):**
1. **B0** (S): fgm's fixture store + a uiload profile shaped like their tree (5 levels,
   20k runs a launch, ~10⁴ live). Baselines for `experiments-status`, the summary and
   a minute-keyed `ago()` count at 588k.
2. **API1** `create_runs` (M) ∥ **API2** `release` + `on_sigterm` + row fields +
   timeline `released` (M) ∥ **API3** out-of-pod finish/notes (S). Optuna goal fix (S).
3. **A0** store-side settings (M).
4. **P1** attention queries + `ago()` + per-job counts (M; after A0 for stores).
5. **P2** progress metric (S-M).
6. **N3** baseline compare (L; after P1).

**Phase 2 (Review and the breakdowns):**
7. **N2** pivot + settled caching (M + M + S panel).
8. **P3** split tallies (M) → **FS** field sort (S-M) → **N4** queue/ratio (M).
9. **P4** team views + `t:` columns (S-M; after A0, FS).
10. **T2b** `outlived` (S).

**Phase 3 (the tree, the feed):**
11. **N6** tree (L; after P1-P3, N4) + the Live/Review presets (S).
12. **T2a** `/metrics` gauges (S-M; after Appendix A keep-warm).

**Phase 4 (last):** N5 overlay and ranges (M), N8 display hint (S-M), N7 note
signatures (M-L, re-scoped after API2), N1 ancestor fields (M), the heartbeat env vars
and conditional beat (S, S-M). T2c is deferred.

Parallelism: API1, API2, API3, A0, P2, N5 and N8 touch disjoint code and can run as
parallel worktrees. P1 → N3 and P3 → FS → N4 → N6 are chains.

## 8. Decisions

Open:
- **D1. Where a store workspace's app settings live (A0).** Recommended: a `settings/`
  store area, journaled, editable by CLI and by a server editor, so storage stays the
  source of truth and CLI/SDK readers see the same schema. The alternative,
  `server.yml` per-workspace `apps:`, is server-only.
- **D2. A released run's status.** Recommended: derive `created` (waiting) from
  `state: released`, with no new D12 status. It is shown as `waiting · released 3m
  ago`. Settled under an ended parent as `lost`.
- **D3. Relative time syntax.** Recommended: `ago("1h")`, a function like `under()` and
  `similar()`. Considered: bare `-1h` literals.
- **D4. Progress names.** Recommended: the conventional metric names `progress` /
  `progress_total` + `run.set_progress`, with a settings mapping for other names.
- **D5. N7's scope.** Recommended: decide after API2 ships and fgm replays incident 2.

## 9. Out of scope

- Ingesting cost data (Kubecost) or pod logs. fgm logs costs as metrics and the pod log
  as a `log_uri` tag/param. The run page links it.
- An alerting engine. Grafana alerts on T2a's gauges; `vmn-exp watch` keeps its sinks.
- Scheduling, retrying or evicting pods. vmn records; fgm's orchestrator acts
  (copy-first, plan 20).
- Full-text search over notes or pod logs across runs (N7 is signatures only).
- Derived-column expressions (T2c) and two-field nesting in the board's Group by (N2
  is a separate pivot, not nested groups).

## Appendix A. Ops issues from the same week (in progress elsewhere)

Reported by the reviewer from a soak test of fgm's store (588k runs). They bear on Live
and T2a. Another agent is fixing them in code now. They are listed here with their
status, not designed.

| # | Issue | Status |
|---|---|---|
| 1 | The refresher stops 60 s after the last request (`ui/refresher.py:IDLE_SEC = 60`). An unwatched server's index stays partial (153k of 588k runs during the soak), and the store upkeep (child markers, compaction of failed/stuck runs) stops with it. A feed meant to alert "without anyone watching the UI" (T2a) would serve stale numbers. | **In progress**: a keep-warm option. T2a waits for it. |
| 2 | S3 `SlowDown` throttling failed refreshes and compactions after 4 retries (on 3.15t). | **Fixed on master** in `689a37ad`: a throttled read sets that record aside, the refresher/journal back off, and retries are adaptive. **Follow-ups in progress:** a listing failure no longer resets the sweep; freshness reports set-aside records; remote workers don't re-read refused records. Q4's request budget is the client half of the same problem. |
| 3 | A `cache_tidy.tick()` start race: an unlocked check-then-start (`ui/cache_tidy.py:31-40`, confirmed at `3d71ee63`), called from concurrent request threads, answered a 500 (a `RuntimeError` from starting the same thread twice). | **In progress.** |
| 4 | Upgrades and cold starts: 0.1.22's schema change wiped the index on upgrade (fixed in 0.1.23, `835cd2ed`). A cold index hung every request until its first publish, about 1 h 50 min there. 0.1.23's merge T (`42c44969`, `dd553eee`) serves a cold remote index from its first 500-record chunk; whether 0.1.24 still blocks a request on a cold start is being checked. | **In progress** (verify, fix if it still blocks). |
| 5 | Logs need timestamps and the failing record's key (the reviewer had to work out `.vmx` run keys from diag dumps). | **In progress.** |
