# Plan 34: fgm after 0.1.36: attempts, baseline peers, lost runs

> fgm's 0.1.36 report (2026-11-10). The upgrade went in place with no extra
> disk, but the board showed no rows for ~8 minutes after the restart
> (`indexing: loaded 0, total null`). Three questions came with it.
>
> Paths: `core/` = `packages/vmn-exp-sdk/src/vmn_exp/core/`; `ui/` =
> `packages/vmn-exp/src/vmn_exp/ui/`; web = `packages/vmn-exp/webui/src`.

Status: **in progress** (2026-11-10).

## 1. Grouping attempts of one training (decided: pool, latest wins)

A resumed training is split across several launch runs: 45 outer rows are 15
trainings. Grouped Outer runs (`group=tags.launch_id`) today show a group
header that aggregates each outer run's value (a median of medians).

- The group header aggregates the **units of all the group's outer runs,
  pooled**: the same `job_agg`, `by`, `value` and `metric` as the rows.
- A unit (e.g. a date by `field:params.trade_date`) found in several attempts
  counts once, from the **latest attempt** (by the outer run's start, else its
  creation). The title names it: `median of 16 dates' own date.best_value · 3
  from earlier attempts`. A duplicate inside one attempt stays a conflict, as
  today.
- A **one row per group** toggle (URL `collapse=1`, also in team views)
  collapses each group to its header row: the pooled value, its coverage
  (`n/of`), and status counts summed over the attempts.
- `job_aggregates` in the grouped answer carries the pooled stats plus
  `from_earlier` (the units taken from earlier attempts).

## 2. Baseline peers that must differ (decided: `baseline.differ`)

The chip pairs a launch with the previous attempt of the same training, which
ran other dates ("0 of N paired").

- `ui.baseline: {match: [tags.target], differ: [tags.launch_id], children_by: …}`.
  A peer must equal the run on every `match` field and differ on every
  `differ` field. A run missing a `differ` field is no peer (missing is
  missing). Checked on save (`core/app_settings.py`).
- Done: `baseline_differ` (a field in both lists is refused),
  `choose_baseline(..., differ)` for the card, chip and experiments-baselines,
  the body's `differ`, and the card's "with the same … and a different …".

## 3. Lost runs and tree status (decided: lost is its own state)

29 launches that exited 0 read `failed` because a few trial batches were
lost (e.g. 1 of 20,591). Lost = stuck under an ended outer run.

- `tree_status` reads `failed` only for real failures (an exit code other
  than 0) below. A tree whose only bad runs are lost reads its own status,
  plus a `lost` count (e.g. `succeeded · 1 lost`). A new `lost_below`
  field is queryable (`lost_below > 0`), and a **lost** chip beside
  **failed** on the board filters by it.
- `failed_below`/`failed_pct` keep counting lost runs: they measure what did
  not finish. Their docs say so.

## 4. The empty board after the upgrade

Under investigation; the fix lands here.
