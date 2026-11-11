# Plan 35: fgm after 0.1.37

> fgm's 0.1.37 report (2026-11-11). Grouping, `differ`, lost vs failed and
> the instant board work for them. Their log showed no "cache schema;
> rebuilding" during 0.1.36's 8-minute gap, only "Index refresh … running for
> 10 min": the slow first load plan 34 §4 fixed. They fixed a producer bug
> (54 of 232 date runs nested under another date run), backfilled, and pruned.
> The store is now 14 trainings / 44 attempts.
>
> Paths: `ui/` = `packages/vmn-exp/src/vmn_exp/ui/`; web = `packages/vmn-exp/webui/src`.

Status: **in progress** (2026-11-11).

## 1. Bugs

1. **Counts.**
   - The "Outer runs (N)" tab label ignores `q`: 44 against the view's 14.
   - A grouped `collapse_all=1` header counts rows, not groups.
   - A bare nav link after the first visit skips the default view, because it is applied once per tab.
2. **A grouped board answers 400 on a job sort.** `group=…&collapse_all=1&sort=job:started`
   gets "needs top=1 or children_of" with `top=jobs`: `ui/leaderboard_group_cache.py:45`
   calls `check_job_sort(sort, False)`.
3. **The Models page** takes ~45 s for 241 models / 7.7k versions.
4. **A model's `artifact_uri`** joins the run path to an absolute `s3://` path.
5. **Stamp tree, Actions and Config** show in the nav of a store-only workspace.
   Kept by design (plan 19 §1.2): Stamp tree and Actions are disabled there
   with the reason "store workspace: no checkout". There is no Config item;
   Settings is the store's own settings page.

## 2. Nested carriers (decided: an option, and the default says so)

`by=field:<k>` stops at the first carrier on each branch.
- `ui.job_aggregate.nested: true` (URL `job_agg_nested=1`) counts carriers at
  any depth. The same value twice is still a conflict.
- By default, the title names the carriers left out:
  `median of 11/14 dates · 3 nested under another date, not counted`.

## 3. A finalise-only attempt's baseline (decided: honest text plus a training pool)

- The chip for a run with no `children_by` runs of its own says so: "this
  attempt has no trade_date runs of its own". It never says "no value
  finished yet".
- `ui.baseline.pool_by: tags.launch_id` compares a run through its
  training's pooled units, the latest attempt winning (as in plan 34 §1). A
  finalise-only attempt then gets a baseline from its training's dates. Its
  peers are other trainings (`differ` applies to the pooled group).
