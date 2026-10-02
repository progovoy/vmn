# Plan 8 (remaining): `watch(model)` — gradient/parameter histograms for plain torch

> Master already has `log_image` / `log_table` / `log_histogram`
> (`packages/vmn-exp-sdk/src/vmn_exp/sdk/run_media.py`, `.../core/histogram.py`,
> `.../core/media.py`; UI `packages/vmn-exp/src/vmn_exp/ui/readers/parsed_logs.py` +
> `webui/src/components/MediaHistograms.tsx`). Only W&B's `wandb.watch(model)` equivalent is
> missing — plain `torch` has no `fit()` for autolog (`docs/sdk.md` "Plain `torch` is
> deliberately not a framework").

## Current histogram format and indexing (verified)

- `run.log_histogram(name, values, step=None, bins=64)` (`run_media.py:182`) -> `core/histogram.histogram()` -> one entry per call: `{"timestamp", "type": "histogram", "name", "step", "bins": [edges, len = counts + 1], "counts": [...]}`. Returns without logging (warning) when no finite values. Auto step = one past the name's last step (`_media_step`/`_logged`); an explicit step must be a non-negative int.
- `core/histogram.py` accepts torch tensors only by `values.detach().cpu().numpy()` -> a **full device->host copy of every tensor**, then numpy `histogram` over `[min, max]` (constant widened +-0.5, last bin closed).
- Indexing is **per name**: `MediaIndex` (`core/media.py`) gives each histogram name a `_ThinnedSteps` that keeps <= `2 * MAX_HISTOGRAM_STEPS` (200) steps as they arrive (stride doubling), plus an int-only rank per step seen; the view serves <= 100 evenly spaced steps, first and last always included. No histogram data goes into the sqlite experiment index — `MediaIndex` is built from the log by `sdk/reader.get_run` and the UI's `parsed_logs._Parsed` (incremental, only changed names rebuilt).
- **Per-name entries are fine; no batched multi-name entry.** Index/thinning cost scales with names x kept steps, which a batched entry would not change; the bytes are the `bins`/`counts` payload (~1.9 KB JSON per 64-bin entry, of which per-entry overhead is ~5%). A batched type would also need new handling in `MediaIndex`, the fold, the reader and the UI. Watch logs one ordinary `histogram` entry per tensor.

## Design

- New `packages/vmn-exp-sdk/src/vmn_exp/integrations/torch_watch.py` (~200; not `torch.py`, which would shadow the package), next to `hf.py`, `optuna_study.py`, `ray_tune.py`. Integrations are part of the SDK distribution (`tests/test_packaging_split.py`); the SDK may import them lazily (`sdk/autolog_hf.py` already does). Keeping it out of `Run` is a choice (framework code stays in integrations), not an import-rule requirement.
- `watch(model, log="gradients"|"parameters"|"all", freq=1000, bins=64, run=None, prefix="") -> Watcher`; `unwatch(model_or_watcher)`.
- **Default `freq=1000`** (W&B default). Size math at 64 bins (~1.9 KB/entry): resnet50 (~161 parameter tensors) is ~310 KB of log per logged step per mode; over 100k train steps that's ~31 MB for gradients at `freq=1000` (~62 MB for `all`), ~310 MB at `freq=100`.
- A forward-pre-hook counts forward calls only while `model.training`. On `calls % freq == 0`: flush pending gradient histograms from the previous pass, log `parameters/<name>` under `no_grad`, arm gradient capture.
- `param.register_hook` computes the gradient histogram on-device while armed (no tensor kept) and returns None (gradient untouched). Hooks may run on autograd engine threads, so they only stash results; **all `run.log_histogram` calls happen on the training thread** (next forward-pre-hook, `Watcher.flush()` / `remove()`), which also keeps `RunMedia._media_steps` single-threaded.
- `_tensor_histogram(t, bins)`: lazy torch; flatten -> finite mask -> `aminmax` -> `histc(min, max)`; constant widened +-0.5 to match `core/histogram.py`; CPU retry if `histc` fails on a device (MPS); one `.tolist()` sync per tensor only on logged steps.
- Logging path: extend `log_histogram` to accept a precomputed `{"bins": edges, "counts": counts}` mapping as *values* (validated: `len(bins) == len(counts) + 1`, like W&B's `np_histogram=`). Watch passes its own `step` (train-mode forward count). No private Run API, no new entry type.
- Run resolved as `run or current_run()` **in the forward-pre-hook** (training thread; `current_run()` from an engine thread only works via the single-open-run fallback). No run, or a rank > 0 (`NoOpRun` is never registered as open, so `current_run()` is None) -> nothing recorded. Hook bodies wrapped in `core.best_effort.quiet(logger)`. Re-`watch` replaces the previous watcher (WeakKeyDictionary). Importing never imports torch.

## Tests first

- `tests/test_torch_watch.py` (importorskip torch): `test_import_does_not_import_torch` (subprocess), `test_gradients_logged_every_freq_steps` (freq=2, 4 steps -> steps 2 and 4, `sum(counts) == numel`), `test_parameters_mode_logs_only_parameters`, `test_all_mode_logs_both`, `test_eval_mode_forward_is_not_counted`, `test_no_open_run_records_nothing_and_training_works`, `test_hook_failure_never_breaks_backward`, `test_gradients_are_unchanged_by_hook`, `test_rewatch_replaces_hooks`, `test_remove_detaches_all_hooks`, `test_tensor_histogram_matches_core_histogram_bins`, `test_entries_index_per_name_with_thinning` (via `core.media.media_index`).
- `tests/test_sdk_media.py`: `test_log_histogram_accepts_precomputed_bins_counts`, `test_log_histogram_rejects_mismatched_precomputed_lengths`.
- Import boundary: `tests/test_packaging_split.py` already covers `vmn_exp/integrations` (no `version_stamp.*`, no full-platform imports); optionally add `"torch"` to `_HEAVY_MODULES` in `tests/test_exp_import_boundary.py`.

## Docs

`docs/sdk.md` "PyTorch — `watch`" (modes, freq, key names `gradients/<param>` / `parameters/<param>`, step = train-mode forward count, AMP scaled-grads caveat, DDP rank-0 only, size guidance) and the precomputed `log_histogram` form in the rich-logging table; replace the "Plain `torch` is deliberately not a framework ... log explicitly" paragraph's advice with a pointer to `torch_watch.watch(model)`; `CLAUDE.md` autolog bullet: replace "Plain `torch` has no `fit` to wrap — use explicit `run.log_metric(...)`" with `vmn_exp.integrations.torch_watch.watch(model)`. Disambiguate from the unrelated `vmn-exp watch` (alerts) CLI.

## Risks / open questions

- UI payload: run detail embeds every histogram name's served steps (`ui/readers/experiment_detail.py:214` `**snapshot.media`); `all` on resnet50 is ~322 names x 100 steps x ~1.5 KB ≈ 48 MB before gzip. Decide before shipping: a per-name histogram endpoint (detail returns names + totals only), or a lower served-step cap for many-key runs.
- FSDP / `torch.compile` / AMP may give misleading or missing histograms (best-effort, documented).
- The watch step counter differs from user metric steps — offer `step_fn=`? Default freq 1000 vs 100? Default `bins=64` vs 32 (halves log size)?
