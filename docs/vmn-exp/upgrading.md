# Upgrading vmn-exp

vmn-exp and vmn-exp-sdk are released as 0.1.x patch releases only, so a
version number never signals a breaking change. This page does: it lists
every behaviour change (removals included) and every store or index format
change, with the release it shipped in and what to do. The
[changelog](../../packages/vmn-exp/CHANGELOG.md) lists the commits; this page
says what an operator or a user has to know.

## Rules

1. **Every release is a 0.1.x patch.** `release_exp.sh` always bumps the
   patch number. No release carries meaning in its number; this page and the
   changelog carry it.
2. **A behaviour change lands with its row.** A behaviour change is anything
   a user or operator could have relied on that now acts differently: a
   documented CLI flag, output or exit code; an HTTP route or response field;
   an SDK call, default or exception; a default view; an environment
   variable; a supported interpreter. The change that makes it adds a row to
   [Behaviour changes](#behaviour-changes) in the same commit series, with the
   version it will ship in (the next release: the pyproject version's patch
   plus one), and at least one of its commits is marked with `!`
   (`fix(sdk)!: ...`) so the changelog lists it under 'Behaviour changes'.
3. **No deprecation period.** An old call, flag, route, name or default is
   removed or made an error at once, in the change that replaces it, with no
   warning stage. That change adds its row to
   [Behaviour changes](#behaviour-changes), saying what to use instead, like
   any other behaviour change. Security fixes and guards that reject input
   which was silently wrong follow the same rule.
4. **Format changes.**
   - An *in-place index bump* (the cache's records or derived version,
     upgraded in place as [server.md](server.md#upgrades) describes) gets a
     row in [Formats](#formats) in the same change.
   - A *store layout* or *record format* change, or an index upgrade that
     *reloads* from storage, also names an earlier release in its
     'Announced in' cell: this page carried a 'planned' note for it in a
     release that shipped before. Its row states the cost (time per 100k
     runs, free disk, what stops serving meanwhile) and the operator's steps,
     and its commit is marked `!`. So the notice is always at least one
     release old when the change ships.
   - *Upgrade order*: the server and CLI first, job images after. A reader
     reads every older record of its layout and record format; a record of a
     newer format is skipped with a warning that says to upgrade vmn-exp, and
     a store of an unknown layout is refused.
5. **1.0 is not promised.** Nothing here is a stability guarantee beyond
   these rules.

`packages/vmn-exp/tests/test_upgrading_md.py` checks the Formats table
against the code's format constants. Behaviour rows are checked in review.

## Behaviour changes

Newest first.

| Version | Date | What changed | What to do | Plan item |
|---|---|---|---|---|
| 0.1.38 | 2026-11-11 | UI: `GET .../experiments/{verstr}/baselines` names `base` for a run that captured only untracked files (it named `base` only for a working-tree or local-commits patch). So the run page's Changes card opens such a run on its own untracked file list, also when it has a previous run (it opened on the diff against the previous run, or said "No code changes captured" without one) | Nothing; the previous-run diff is one click away in the baseline picker | [39 B4c](../plans/39-vmn-exp-cli-surface.md#b4c) |
| 0.1.38 | 2026-11-11 | SDK: a run left open at interpreter exit after `sys.exit(N)` (N not 0) is recorded failed with exit code `N`; it read succeeded. The first `start_run()` wraps `sys.exit` to learn `N` (main thread only; one made before the run opened is forgotten). A hand-written `raise SystemExit(N)` and `os._exit(N)` still read succeeded | Nothing; a job that ended in `sys.exit(N)` now shows failed, as its exit code said, and alerts, sweeps and baselines see it so. For the two unseen exits use `with start_run(...)` or `run.finish(exit_code=N)` | [40 C8](../plans/40-vmn-exp-sdk-write-path.md#c8) |
| 0.1.38 | 2026-11-11 | SDK: `import vmn_exp.sdk` no longer replaces `sys.excepthook` or registers an atexit handler; both are installed by the first `start_run()`. So the finalizer of a run left open now runs before the storage's own exit flush (it ran after it), and that flush ships what the finalizer wrote. The SIGTERM handler is still installed at import, but with no open run it hands the signal on at once without starting a finalizer thread | Nothing. Code that compared `sys.excepthook` after importing the SDK sees its own hook until a run opens | [40 C9](../plans/40-vmn-exp-sdk-write-path.md#c9) |
| 0.1.38 | 2026-11-11 | Direct to a bucket (no `VMN_EXPERIMENT_DIR`): a finished run's log buffer (`vmn-log-buffer-<id>` in the temp dir) is removed only once the bucket holds a final `run_state.yml`; until then the exit flush uploads the buffer's final state once more, and when that fails keeps the buffer with a warning naming it and the run. Before, the buffer, the only local copy of the final state, was removed as soon as the logs had shipped, and a failed state upload left the run `running` for good | Nothing; a warning that names a kept buffer and a run means that run's final state is in that directory | [40 C13](../plans/40-vmn-exp-sdk-write-path.md#c13) |
| 0.1.38 | 2026-11-11 | SDK, direct to a bucket (no `VMN_EXPERIMENT_DIR`): a run's log lines and metric blocks are shipped by its `vmn-exp-sync` thread, never by the thread that logs or the heartbeat, so a hung store no longer stalls `log_metric`. The first lines reach the bucket moments after `log_metric` returns, not before | Nothing; a reader that needs everything logged reads after `finish()`, as before | [40 C3](../plans/40-vmn-exp-sdk-write-path.md#c3) |
| 0.1.38 | 2026-11-11 | On a bucket store workspace, an edit whose upload failed is pending: its failed job says `The edit is kept on the server and is pending until it ships`, and the next action on the workspace uploads it first. While that upload still fails, the new action does not run and fails with `An earlier edit is still pending`. Before, the edit stayed in the server's buffer unannounced and reached the store later, or twice if repeated | Do not repeat a pending edit; run any action on the workspace once the store answers, and it ships first | [40 C16](../plans/40-vmn-exp-sdk-write-path.md#c16) |
| 0.1.38 | 2026-11-11 | A store workspace's edit job whose store call does not return within the job timeout (30 minutes; for a bulk action, per batch of 500) now fails with exit code `-1` and `Job timed out after 1800s: the store did not answer`, instead of reading `running` for as long as the store hangs. Until the late call returns, a new action on that workspace answers `409` `The previous action is still waiting for the store` (was `Another action is already running in this workspace`) | Retry the action once the store answers again; a client that matched the old `409` text matches the new one too | [40 C16](../plans/40-vmn-exp-sdk-write-path.md#c16) |
| 0.1.38 | 2026-11-11 | SDK: under SIGTERM the final uploads are waited for 25 s, not 60 s (`finish()` and exit keep 60 s), and media files still uploading get at most half of that | A job whose scheduler grants more than 30 s and that needs the longer wait sets `VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC` (it sets both waits) | [40 C7](../plans/40-vmn-exp-sdk-write-path.md#c7) |
| 0.1.38 | 2026-11-11 | With authentication on, `GET /api/v1/jobs/{id}` answers `404 Job not found` unless the caller is a viewer of the job's workspace in the job's org; before, any role in any workspace could read any job | Poll a job with a token or session that has a role in the workspace that ran it | [42 E6](../plans/42-vmn-exp-server-security-api.md#e6) |

## Formats

Newest first. Releases before 0.1.30 rebuilt the cache on every index
change.

| Version | Store layout | Record format | Index records | Index derived | Upgrade | Cost and operator steps | Announced in |
|---|---|---|---|---|---|---|---|
| 0.1.36 | 2 | 2 | 20 | 21 | in place | Runs with compacted metrics logged twice are re-checked in the background; nothing to do ([server.md](server.md#upgrades)) | — |
| 0.1.35 | 2 | 2 | 19 | 21 | in place | Runs with a param named like a logged metric are re-read; the rest re-derive, about a minute per 100k runs; nothing to do | — |
| 0.1.30 | 2 | 2 | 18 | 19 | in place | Baseline | — |
