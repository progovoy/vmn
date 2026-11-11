# Plan 37: vmn-exp review fixes (index)

> A product review of vmn-exp on 2026-11-11 (hands-on quickstart, SDK,
> dashboard and restore, plus code reviews of the SDK, the server/UI and the
> docs) produced about 60 findings. This plan covers all of them. It is an
> index: the items live in seven workstream plans (38-44), and this file holds
> what only makes sense across them: the order, the conflicts, the decisions
> that are the owner's, and what stays open.
>
> How it was made: one planner per workstream read the code and drafted items;
> a critic per workstream re-checked every citation, looked for tests that pin
> today's behaviour and revised the draft; a last pass read the seven plans
> together. Nothing was implemented by that process. Measurements quoted in
> the plans are the planners' own and are marked as such there.

Status: **proposed** (2026-11-11).

Solo impact: milestone M2 exists for the solo user (one run per script, a
quickstart that works as pasted); no item may make the single-user case worse
(see F13 in plan 43).

## Already landed

Two findings were fixed before planning, test first, each as its own commit:

- `859da19b` `fix(ui): reject option-like metric names in job actions`. A
  metric name such as `--attach` in an `exp_create`/`exp_add` request body was
  parsed as a flag of the `vmn-exp` subprocess and could attach a server file
  to a run. E1 (plan 42) builds the general choke point on top of it.
- `59becdd5` `fix(sdk): keep the log buffer when the final ship fails`. A
  direct-to-bucket run whose store was unreachable at close lost the only copy
  of its unshipped lines; a finished run's log sync also removed the buffer
  while metric blocks were unshipped. Nothing re-ships a kept buffer yet: C5,
  C6 and C13 (plan 40) are the follow-ups.

## What planning changed in the review

The critics refuted or narrowed about 50 statements; each workstream plan
lists its own under "Review findings corrected or dropped". The ones that
change priorities:

- **New P0, not in the review:** the artifact download and table routes follow
  symlinks out of a run's record directory, so anyone who can write into a
  run's `artifacts/` on a shared filesystem can make the server hand any
  viewer a file the server user can read (E9, plan 42).
- **Worse than reported:** the older UI job actions are not protected by
  argparse. It accepts negative-number tokens and any token with a space as an
  option value, and `prune` renders `keep` unchecked (E1).
- **Narrower than reported:** only the *final* run state and final log sync
  are lost on a failed write; heartbeats repair themselves on the next beat
  (C1). Inline remote PUTs on the caller's thread exist only in
  direct-to-bucket mode (C3).
- **Wrong:** `--json` already exists on `model` and `lineage`; usage errors
  already exit 2; `/metrics` does require a viewer when auth is configured;
  `/apps` and the reports list are cached, not store walks; unhashed bundle
  names are by design; skipping the OIDC signature check is a documented
  choice the spec permits over TLS (the missing part is enforcing https, E2).
- **Not reproduced in absolute terms:** `vmn-exp run` overhead. The planner
  measured 0.43 s alone against 1.0 s wrapped (about 2.3x), not 1.5 s against
  5 s; the fixed 0.5 s poll sleep is the main cause (B9b), imports and the
  env probe are not.
- **Not feasible as stated:** moving `index*`/`similar*`/`query*` out of the
  SDK wheel (the SDK's reader API imports them); the fix is lazy imports with
  an import-budget test (D1, D2). Relaxing the `vmn-exp-sdk==` pin is unsafe
  and unnecessary: it does not constrain SDK-only job images (F11).
- **Overstated:** the flat `experiment` parser is not the root cause of the
  injection; `start_run`'s body is about 64 lines, the trap is its 25
  positional parameters (D5); `list_runs` is oldest-first only without a
  primary metric (D9).

## Plan numbering

37 is this index and 38-44 are the workstreams (36 was taken upstream by the
fgm 0.1.37 plan). The `36-*` plan docs the planners each proposed are these
files, so the plan-doc item C12 is dropped in plan 40, and the roadmap decision
record is F14 itself in plan 43, with no separate roadmap file. Each file's
title carries its own number, and rows 37-44 are in
[README.md](README.md).

## Workstreams

Counted from each file's Items table on 2026-11-11, after the rework. "Decided"
counts the rows marked decided, which are the items an owner answer shaped.

| Plan | Workstream | Items | P0 | P1 | Decided |
|---|---|---|---|---|---|
| [38](38-vmn-exp-first-run.md) | A: First-run experience and onboarding | 11 | 0 | 7 | 4 |
| [39](39-vmn-exp-cli-surface.md) | B: CLI identity, output and surface | 15 | 0 | 6 | 8 |
| [40](40-vmn-exp-sdk-write-path.md) | C: SDK write-path reliability | 15 | 1 | 8 | 10 |
| [41](41-vmn-exp-sdk-shape.md) | D: SDK footprint, API consistency and storage contract | 16 | 0 | 8 | 8 |
| [42](42-vmn-exp-server-security-api.md) | E: Server security, authorization and HTTP API | 23 | 1 | 7 | 10 |
| [43](43-vmn-exp-docs-release.md) | F: Positioning, docs, packaging and release discipline | 16 | 0 | 4 | 12 |
| [44](44-vmn-exp-io-behind-interfaces.md) | G: IO behind interfaces and oversized modules in vmn-exp | 19 | 0 | 1 | 7 |
| | Total | 115 | 2 | 41 | 59 |

Plan 42's 23 rows are 19 items to build and 4 parked (E7b, E5b, E12c2, E12e).
Not counted, because each is a one-line note under "Dropped" or "Parked" in its
file: A11, B5c, B9c, C12, E10 (done upstream), F15 and D17 (parked).

## Milestones

The order after the owner's decisions. M0 runs alongside M1; the E and C chains
of M1 share no files. Each item appears in exactly one milestone. Releases are
0.1.x patch releases throughout: every behaviour-changing item adds its own row
to `docs/vmn-exp/upgrading.md` and a `!` commit (F9).

### M0 Guards and release plumbing

Put the cheap guards and the release rules in place so everything after is checked and logged. Runs concurrently with M1. Nothing here changes product behaviour except E14a's one-off pass that fixes whatever web tests fail today.

Items: [G1](44-vmn-exp-io-behind-interfaces.md#g1), [F4](43-vmn-exp-docs-release.md#f4), [F9](43-vmn-exp-docs-release.md#f9), [F10](43-vmn-exp-docs-release.md#f10), [F8](43-vmn-exp-docs-release.md#f8), [E14a](42-vmn-exp-server-security-api.md#e14a), [D4](41-vmn-exp-sdk-shape.md#d4), [B9a](39-vmn-exp-cli-surface.md#b9a).

Why this order:

- G1 makes the IO rule enforceable for the modules M1-M4 create.
- F4 guards the many doc edits, and its index check requires every new doc (`upgrading.md`, `ui-api.md`, `notebooks.md`, `vmn-vs-wandb.md`) to be linked from `docs/vmn-exp/README.md`.
- F9 creates `upgrading.md`, the removal rule and the format ratchet. Several dozen later items add a row to it, so it lands before the first behaviour-changing release; F10 gives that release a changelog.
- E14a is now the single web-CI item (F15 is a pointer to it): one-off fix pass, a blocking `tests_webui` stage, then ESLint. It lands before the first web-client edit (E8 in M1, A6 in M2).
- B9a records the baseline that A5 and B9d are measured against.
- F8 brings the plans index up to date (rows 37-44 already exist; see [README.md](README.md)).
- E13 is no longer here: it reads the endpoint table from `ui-api.md`, which F5 creates in M4. G18 is deliberately not here (see conflicts).

Parallel worktree groups (each line is one worktree at a time):

- G1 (packages/vmn-exp/tests/io_scan.py, test_io_boundary.py, io_boundary_known.py)
- F4 then F8 (tests/doc_links.py, docs/plans/README.md, test_plans_index.py)
- F9 then F10 (docs/vmn-exp/upgrading.md, tests/upgrading_table.py, release_exp.sh, cliff.toml, Makefile)
- E14a (ci/pipeline.py, ci/test_pipeline.py, Makefile, webui/package.json, eslint.config.js); Makefile is shared with F10, so land E14a's stage first
- D4 (tests/test_docs_sdk_public_names.py, docs/vmn-exp/sdk.md)
- B9a (tests/git_budget.py, tests/test_exp_run_git_budget.py)

### M1 Safety: security and data loss

Close the exploitable or data-losing defects: symlink file disclosure, argv injection and the prune keep=-1 bug, cross-workspace job reads, OIDC transport, frozen roles, a silently lost final state, a deleted buffer, hung-store stalls, wrong run status.

Items: [E9](42-vmn-exp-server-security-api.md#e9), [E8](42-vmn-exp-server-security-api.md#e8), [E9b](42-vmn-exp-server-security-api.md#e9b), [E1](42-vmn-exp-server-security-api.md#e1), [E6](42-vmn-exp-server-security-api.md#e6), [C16](40-vmn-exp-sdk-write-path.md#c16), [E4](42-vmn-exp-server-security-api.md#e4), [E2](42-vmn-exp-server-security-api.md#e2), [E5a](42-vmn-exp-server-security-api.md#e5a), [E12c](42-vmn-exp-server-security-api.md#e12c), [C1](40-vmn-exp-sdk-write-path.md#c1), [C2](40-vmn-exp-sdk-write-path.md#c2), [C7](40-vmn-exp-sdk-write-path.md#c7), [C4](40-vmn-exp-sdk-write-path.md#c4), [C3](40-vmn-exp-sdk-write-path.md#c3), [C13](40-vmn-exp-sdk-write-path.md#c13), [C14](40-vmn-exp-sdk-write-path.md#c14), [C9](40-vmn-exp-sdk-write-path.md#c9), [C8](40-vmn-exp-sdk-write-path.md#c8).

Why this order:

- P0s first (E9, C1).
- E1 is one item in the decided form: every option as `--flag=value` through `ui/job_argv.py`, with the six argv-pinning test files rewritten. Its first commit changes the `--metrics` parser line to `action="extend"`. B5c is not an item any more; plan 39 keeps a pointer to E1.
- C16 (new) follows E6 on ui/jobs.py. It pins that UI store actions ship off the request thread and bounds an in-process job, which is the server half of the hung-store stall.
- The whole sdk/run.py lifecycle chain (C1 -> C7 -> C4 -> C3 -> C9 -> C8) is done here, before A5 adds GuestRun in M2 and before G9 moves the close path in M5. C8 also fixes failed jobs shown as succeeded.
- C2 and C13 land here so that C15 (M2) and C6 (M4) can name a recovery command, and so D3 can move `core/push_*` later.
- The E route and constructor changes land before G4, G6 and G19 restructure server.py.
- G9's characterization tests for the names tests patch on `vmn_exp.sdk.run` (`sync_to_remote`, `compact_by`) are written before C1.

Parallel worktree groups (each line is one worktree at a time):

- E9 -> E8 -> E9b (ui/security.py, ui/readers; E9 also touches the server.py download route and routes_media.py)
- E1 -> E6 -> C16 (cli/plugin.py:87-88, new ui/job_argv.py, ui/jobs.py, ui/jobs_exp_meta.py; E6 also server.py get_job; C16 adds ui/job_calls.py)
- E4 -> E2 -> E5a (ui/cli.py, ui/config.py, ui/auth/*, routes_admin.py)
- E12c (ui/api_errors.py plus one hunk in server.py; serialize server.py hunks with E9 and E6)
- C1 -> C7 -> C4 -> C3 -> C9 -> C8 (sdk/run.py, core/final_retry.py, sdk/log_sync.py; one worktree at a time)
- C2 (core/state_cas.py, core/push_files.py) in parallel with the C1 chain; C13 after C2 and C3 (storage/buffered.py)
- C14 (verify-first test; core/state_cas.py only if red, after C2)
- The E groups and the C groups share no files and run fully in parallel

### M2 First run and everyday CLI correctness

A new user gets one run with its metrics, whether the script is started by `vmn-exp run`, a rerun or a sweep trial; a board that shows those runs; a clear error outside a checkout; a quickstart that works as pasted; and a CLI that says who it is and prints params, untracked files and sorted lists correctly.

Items: [F1](43-vmn-exp-docs-release.md#f1), [F2](43-vmn-exp-docs-release.md#f2), [A2](38-vmn-exp-first-run.md#a2), [A3](38-vmn-exp-first-run.md#a3), [A1](38-vmn-exp-first-run.md#a1), [A7](38-vmn-exp-first-run.md#a7), [A8](38-vmn-exp-first-run.md#a8), [A9](38-vmn-exp-first-run.md#a9), [A4](38-vmn-exp-first-run.md#a4), [C15](40-vmn-exp-sdk-write-path.md#c15), [B9b](39-vmn-exp-cli-surface.md#b9b), [A5](38-vmn-exp-first-run.md#a5), [A12](38-vmn-exp-first-run.md#a12), [A6](38-vmn-exp-first-run.md#a6), [B1](39-vmn-exp-cli-surface.md#b1), [B2](39-vmn-exp-cli-surface.md#b2), [B3](39-vmn-exp-cli-surface.md#b3), [B4a](39-vmn-exp-cli-surface.md#b4a), [B4b](39-vmn-exp-cli-surface.md#b4b), [B4c](39-vmn-exp-cli-surface.md#b4c), [F13](43-vmn-exp-docs-release.md#f13).

Why this order:

- After M1, because A5's GuestRun overrides four methods of the close path M1 rewrites (`_publish`, `_publish_heartbeat`, `_record_final`, `_record_release`).
- C15 (new) sits here, not in M1, for two reasons. It edits `_Supervision` between A4 and B9b, and it needs C1, C3 and C13. It must ship with or before A5: once a run is adopted, its final state is written only by the supervisor, so a silently dropped supervisor upload would lose the run's outcome.
- A5, A12 and A6 are decided and ship together. A5 is on by default with the direct-child rule and the guest writing its own stream. A12 makes rerun and sweep trials adopt. A6 opens an app with no outer runs on the runs board, so an adopted single run shows its metric columns.
- F1 and F2 precede A7 and F5 (the README opening, architecture.md).
- F13 is written against A6's new default board, so it follows A6.
- B1 touches core vmn's parser through an optional argument; coordinate with A2 (also core) and plan 35.

Parallel worktree groups (each line is one worktree at a time):

- F1 -> F2 -> A7 -> A8 (docs/vmn-exp/README.md, vmn-vs-mlflow.md, architecture.md, PRODUCT.md, packages/vmn-exp/README.md, client-guide.md)
- A2 (packages/vmn core/utils.py, tests/) then B1 (core cli/args.py, entry.py, plugin_api.py, api.py, vmn-exp cli/main.py, cli/version.py)
- A3 (sdk/checkout_guard.py, sdk/create.py, sdk/resume.py) -> A9 (docs/vmn-exp/notebooks.md)
- A1 (gitmode/coldstart.py, cli/experiment.py auto_init); serialize with B2/B3 on cli/experiment.py
- A4 -> C15 -> B9b -> A5 with A12 (cli/run.py, cli/supervisor.py, cli/supervisor_state.py, cli/plugin.py, then core/streams.py, core/writer.py, sdk/adoption.py, sdk/guest_run.py, sdk/run.py, cli/rerun.py, cli/sweep/agent.py, cli/sweep/parser.py) -> A6 (webui Experiments) -> F13
- B2 -> B3 (cli/views.py, cli/list_layout.py, cli/experiment.py show/compare/list)
- B4a -> B4b (cli/views.py patch payload, then webui RunChanges*); B4c (ui/readers/patches.py, routes_run_code.py) in parallel

### M3 SDK contract: footprint, API traps, storage plugin contract, compatibility

Make the job-side wheel cheap to import and hard to misuse, give plugin authors a conformance kit, write down the SDK/server compatibility contract and package metadata, and add the code-less run.

Items: [D1](41-vmn-exp-sdk-shape.md#d1), [D2](41-vmn-exp-sdk-shape.md#d2), [D6](41-vmn-exp-sdk-shape.md#d6), [D8](41-vmn-exp-sdk-shape.md#d8), [D5](41-vmn-exp-sdk-shape.md#d5), [D7](41-vmn-exp-sdk-shape.md#d7), [D9](41-vmn-exp-sdk-shape.md#d9), [D10](41-vmn-exp-sdk-shape.md#d10), [D11](41-vmn-exp-sdk-shape.md#d11), [D16](41-vmn-exp-sdk-shape.md#d16), [D12](41-vmn-exp-sdk-shape.md#d12), [D15](41-vmn-exp-sdk-shape.md#d15), [C5](40-vmn-exp-sdk-write-path.md#c5), [C10](40-vmn-exp-sdk-write-path.md#c10), [C11](40-vmn-exp-sdk-write-path.md#c11), [F11](43-vmn-exp-docs-release.md#f11), [F12](43-vmn-exp-docs-release.md#f12), [A10](38-vmn-exp-first-run.md#a10).

Why this order:

- After M1 and M2, so the modules they add (core/final_retry, sdk/log_sync, process_hooks, exit_code, checkout_guard, adoption, guest_run) are counted when D1 sets the import budget, and so D5 and D6 change a `start_run` and a `resume.locate` that A3 and A5 have finished changing.
- D5, D7, D9 and D11 are two steps each: warn now, remove later per F9's removal rule. Step 1 is in this milestone. Step 2 waits out the rule and is the same item.
- D12 seeds its probe table after C3 and C15, so `defer_ships` is its one new row.
- C5 follows C13 on storage/buffered.py.
- A10 starts with its spike (the verstr shape, and whether `RECORD_FORMAT_VERSION` changes). The build follows the spike, after D5 so `code=` enters `start_run` as a keyword-only parameter, and before F11 records the golden record.
- F11 and F12 need F9 and F10 from M0. D15 stage 1 (real GCS/Azure SDKs in the test requirements) precedes F12's lower bounds. F12 starts with the job-image interpreter check.

Parallel worktree groups (each line is one worktree at a time):

- D1 -> D2 -> D10 (sdk/__init__.py, core/refs.py, _base.py, storage/ship_state.py, new sdk/store_resolve.py)
- D5 -> D7 (sdk/positional.py, sdk/run.py signature, sdk/reader.py, run_artifacts.py, run_media.py); D9 after D7 (sdk/reader.py)
- D6 (sdk/resume.py, one line in run.py); serialize with D5 on run.py
- A10 spike any time; A10 build after D5 and D6 (sdk/create.py, sdk/codeless.py, docs/vmn-exp/notebooks.md)
- D8 (sdk/metric_defs.py, sdk/ranks.py)
- D11 -> D12 (storage/base.py, storage/conformance.py, tests); D15 stage 1 after D11 (tests only)
- D16 (docstrings, storage/stream_listing.py, cached_logs.py, cached_metrics.py)
- C5 (storage/host_dirs.py, storage/buffer_owner.py, storage/buffered.py, storage/open.py, client-guide.md recipe)
- C10, C11 (docs only)
- F11 (docs/packaging.md, tests/golden) and F12 (pyproject files, uv.lock); F12 after D15 stage 1

### M4 CLI surface, server API, docs and roadmap features

Finish the non-urgent surface work: the HTTP API in its own doc, flag ownership with per-action help, `--json`, exit codes, ui subcommands, one error envelope, the body-type sweep, JWKS verification, the buffers recovery command, object-store batch deletes, the SDK wheel move, and the three roadmap features the owner chose to build.

Items: [F5](43-vmn-exp-docs-release.md#f5), [E13](42-vmn-exp-server-security-api.md#e13), [B6](39-vmn-exp-cli-surface.md#b6), [B5a](39-vmn-exp-cli-surface.md#b5a), [B5b](39-vmn-exp-cli-surface.md#b5b), [B5d](39-vmn-exp-cli-surface.md#b5d), [B7](39-vmn-exp-cli-surface.md#b7), [B8](39-vmn-exp-cli-surface.md#b8), [B9d](39-vmn-exp-cli-surface.md#b9d), [C6](40-vmn-exp-sdk-write-path.md#c6), [E7](42-vmn-exp-server-security-api.md#e7), [E12b](42-vmn-exp-server-security-api.md#e12b), [E12a](42-vmn-exp-server-security-api.md#e12a), [E11](42-vmn-exp-server-security-api.md#e11), [E12d](42-vmn-exp-server-security-api.md#e12d), [E3](42-vmn-exp-server-security-api.md#e3), [E14b](42-vmn-exp-server-security-api.md#e14b), [E14c](42-vmn-exp-server-security-api.md#e14c), [D13](41-vmn-exp-sdk-shape.md#d13), [D14](41-vmn-exp-sdk-shape.md#d14), [D3](41-vmn-exp-sdk-shape.md#d3), [F3](43-vmn-exp-docs-release.md#f3), [F6](43-vmn-exp-docs-release.md#f6), [F14](43-vmn-exp-docs-release.md#f14), [F16](43-vmn-exp-docs-release.md#f16), [F17](43-vmn-exp-docs-release.md#f17), [F18](43-vmn-exp-docs-release.md#f18).

Why this order:

- F5 first, in one commit: it moves the HTTP API from `ui.md` to `ui-api.md`. E13 follows it and reads the endpoint table from the new file; the API text of E12b and E12d goes there too.
- B6, A4 (M2) and E1 (M1) precede B5a, so the ownership table contains `compare --json`, `--no-adopt` (run, rerun, sweep agent) and every flag the UI builder emits. B5b and B5d ship in one release: exit 2 for a flag the action does not own, and per-action `--help` to tell the user what it does own. B7 follows B5b on cli/experiment.py.
- B9d starts only after A5 and A12 have shipped: it re-measures first, then trims redundant git calls one commit each.
- C6 needs C5, C2 and C13. It ships only buffers whose owner lock it can take.
- D3 lands after C2 and C6 (they edit and add `core/push_*` modules and tests D3 repoints) and before G11 Part A, G13 and G16 cite the moved modules.
- E3 follows E5a on ui/cli.py; B8 follows E3 there and B5a on cli/plugin.py.
- E7 is docs plus the web client only (a 404 poll reads as unknown).
- D13 and D14 need D15 stage 2 (the emulator CI stage), which is done here as the second half of D15.
- F16, F17 and F18 (new, from the F14 answers) are last. F17 edits cli/sweep/agent.py after A12, and F18 adds two methods to sdk/run.py and pairs with A9's notebook guide. All three land before M5 moves those files. F14 is the decision record and needs only F8.

Parallel worktree groups (each line is one worktree at a time):

- F5 -> E13 (docs/vmn-exp/ui.md, ui-api.md, cross-doc links, test_docs_similar_statements.py, tests/test_docs_ui_endpoints.py)
- B6 -> B5a -> B5b with B5d -> B7 (cli/compare_view.py, cli/exp_parser/*, cli/plugin.py, cli/main.py, cli/experiment.py, cli/settings.py)
- E3 (ui/auth/jwks.py, oidc.py, cli.py wiring, tests/oidc_test_keys.py) -> B8 (ui/cli_parser.py, cli/plugin.py ui parser block; after B5a on plugin.py)
- B9d (gitmode/coldstart.py, gitmode/checkout.py, budget test)
- C6 (core/buffer_recover.py, cli/buffers_cmd.py, storage/buffered.py reopen); plugin.py registration after B8
- E12b -> E12a (ui/api_errors.py, route modules, webui http.ts)
- E11 (routes_reports.py, routes_admin.py, routes_models.py), E12d (ui/leaderboard_params.py, routes_leaderboard.py), E7 (docs, webui jobPoll.ts, components/ui.tsx): disjoint, parallel
- E14b, E14c (webui vite config; webui pages/StampTree): parallel
- D15 stage 2 -> D13, D14 (ci/pipeline.py, storage/object_client.py, gcs.py, azure.py)
- D3 a/b/c as three worktrees (reports/ move; registry/cli* to cli/model_cmd.py; core/push_* to cli/pushing/), after C6
- F3 (vmn-vs-wandb.md), F6 (experiments.md names, stuck formula), F14 (plan 43 and vmn-vs-mlflow.md)
- F16 (sdk/autolog_gbdt.py), F17 (core/sweep/early_stop.py, spec.py, cli/sweep/agent.py), F18 (sdk/run_repr.py, sdk/run.py): disjoint, parallel

### M5 IO behind interfaces and oversized modules

Ports, fakes, the no-Docker unit lane, composition roots for UI, CLI and SDK, then clock, processes, env, random, console and filesystem migration by value, the status clock migration, a size ratchet, and the server, experiment, run and index splits.

Items: [G2](44-vmn-exp-io-behind-interfaces.md#g2), [G3](44-vmn-exp-io-behind-interfaces.md#g3), [G18](44-vmn-exp-io-behind-interfaces.md#g18), [G4](44-vmn-exp-io-behind-interfaces.md#g4), [G19](44-vmn-exp-io-behind-interfaces.md#g19), [G5](44-vmn-exp-io-behind-interfaces.md#g5), [G7](44-vmn-exp-io-behind-interfaces.md#g7), [G8](44-vmn-exp-io-behind-interfaces.md#g8), [G6](44-vmn-exp-io-behind-interfaces.md#g6), [G9](44-vmn-exp-io-behind-interfaces.md#g9), [G10](44-vmn-exp-io-behind-interfaces.md#g10), [G11](44-vmn-exp-io-behind-interfaces.md#g11), [G12](44-vmn-exp-io-behind-interfaces.md#g12), [G15](44-vmn-exp-io-behind-interfaces.md#g15), [G16](44-vmn-exp-io-behind-interfaces.md#g16), [G13](44-vmn-exp-io-behind-interfaces.md#g13), [G14](44-vmn-exp-io-behind-interfaces.md#g14), [G17](44-vmn-exp-io-behind-interfaces.md#g17).

Why this order:

- Last among the build milestones, because it restructures the files M1-M4 change (sdk/run.py, cli/run.py, cli/experiment.py, ui/server.py, ui/jobs.py, storage/buffered.py). Doing it earlier would force every fix to be rebased across moved code.
- G18 lands here, right before the splits.
- G8 injects io into B9b's `watch()` and A4's `supervised_env`, and C15's retry takes its sleep and deadline from the injected clock. It adds no second tick extraction.
- G11 is both parts. Part A is the sdk defaults. Part B is the status clock migration, a three-commit series (accept, migrate tests only, remove) over 119 patch sites in 95 test files; it needs G4, G7 and G10, and its third commit adds an `upgrading.md` row because `derive_status` then requires `now`.
- G17 is the real `core/index.py` split into mixin modules behind the `ExperimentIndex` facade. It follows G11 Part B and G18, edits no test file, and is gated by the named benchmarks.
- G12 stage B follows G15; stage C follows G17 in the SDK lane.
- G14 step 2 waits for plan 35's MemFS. G7 uses plugin.py shims until plan 35 provides `vmn_ctx.io`.

Parallel worktree groups (each line is one worktree at a time):

- G2 -> G3 (core/ports.py, core/real_io.py, tests/fakes, tests/unit, run_pytest.sh, ci/pipeline.py)
- G18 (tests only) in parallel with G2
- UI lane: G4 -> G5 -> G6, with G19 after G4 and G13 after G19 (ui/app_deps.py, ui/server.py, ui/jobs.py, ui/job_calls.py, ui/auth/*, ui/registry_snapshot.py)
- CLI lane: G7 -> G8, G15 -> G16 (cli/plugin.py, cli/main.py, cli/run.py, cli/experiment*.py)
- SDK lane: G9 -> G10 -> G11 Part A -> G11 Part B -> G17 -> G12 stage C (sdk/run.py, sdk/sysmetrics.py, storage/buffered.py, core/status.py, core/index*.py)
- G12 stage A (ui) follows G7 and G19; stage B (cli) follows G8 and G15
- G14 step 1 any time after G1 and G18; G14 step 2 after plan 35 stage 4
- The lanes share CLAUDE.md lines and the allowlist file (`io_boundary_known.py`, which also holds REAL_WIRED and the `real_io()` caller list). Its edits are per-module entries, so conflicts are trivial, but each lane regenerates it before merging. G11 Part B crosses lanes (ui and cli status callers), so it runs when the UI and CLI lanes are idle.

### M6 Parked

Not started. Each has an owner answer of "not now" and is kept in its plan with "do not start".

Items: [E7b](42-vmn-exp-server-security-api.md#e7b), [E5b](42-vmn-exp-server-security-api.md#e5b), [E12c2](42-vmn-exp-server-security-api.md#e12c2), [E12e](42-vmn-exp-server-security-api.md#e12e), and the parked note [D17](41-vmn-exp-sdk-shape.md#d17).

What would restart each:

- E7b (persist jobs in the control plane): replicas without sticky routing become a real deployment.
- E5b (re-check roles with the IdP): near-immediate deprovisioning is required; after E5a and E3.
- E12c2 (narrow the ValueError handler): one release of E12c's logs shows which errors are client errors.
- E12e (typed request and response models, generated types.ts): vmn-exp is split out, or a second client appears.
- D17 (drop duck-typed storages): a concrete cost appears; D12's table is then the work list.

## Decisions (owner, 2026-11-11)

Answered interactively. Where an answer differs from the planners'
recommendation it is marked **(differs)**; the answer wins over anything the
milestone list, the recommendation list below or a workstream plan still says.

**Process**

| Topic | Decision |
|---|---|
| Releases (F9) | **(differs)** Keep patch releases (0.1.x), no 0.2.0 batch. Every behaviour change gets an `upgrading.md` row and a changelog entry. |
| Test edits | **(differs)** Every test edit named in plans 38-44 is approved up front, including the tests that pin behaviour being changed. Edits not named in a plan still stop and ask. |
| CLAUDE.md | Approved: the docs-layout lines, the no-Docker test lane, and `start_run`/public SDK functions plus the `plugin.py` handler shims as entry points that may build real IO. |
| Plan numbering | 37 index, 38-44 workstreams (done; upstream took 36). |
| Ratchet timing (G1, G18, D1, D12) | Not asked; the recommendation stands (G1 at the start, G18 at the start of M5, D1's budget raised only in a commit naming the added module, D12 seeded after C3). |

**First run (plan 38)**

| Item | Decision |
|---|---|
| A5 adoption | On by default, direct-child rule, `--no-adopt` / `VMN_EXP_ADOPT=0`. The guest writes its own stream. |
| A12 rerun and sweep trials | **(differs)** Adopt too, shipped with A5. |
| A11 cold-start push | Keep pushing when a remote exists, announced (A1 only). A11 is dropped. |
| A10 code-less run | Yes, explicit opt-in only (`code=False` / `VMN_EXP_CODE=none`), after the verstr spike. |
| A6 default board | **(differs)** Change it now: an app with no outer runs opens on the runs board with metric columns. |

**CLI (plan 39)**

| Item | Decision |
|---|---|
| B1 `--version` | **(differs)** Print vmn-exp's own version only. |
| B5b, B5d unowned flags | **(differs)** Exit 2 and per-action `--help` together. No argparse subparsers. |
| B3 sorted `list` | Flat rows with a `^[N]` parent marker when not in storage order. |
| B6, B7 | `--json` on `compare` and `comments` only; exit codes stay 0/1/2 plus the child's code, documented. |
| B4c untracked-only run | Its own file list is the default baseline. |
| B9d run overhead | Re-measure after A5, then trim redundant git calls. |

**SDK write path (plan 40)**

| Item | Decision |
|---|---|
| C3 off-thread ships | SDK runs as planned, plus two new items for the `vmn-exp run` supervisor and the UI server's edit storage. |
| C5, C6 buffers | Per-host state dir (or `$VMN_EXP_CACHE_DIR`) with local-temp fallback; explicit `vmn-exp buffers list|ship`, only for buffers whose owner lock can be taken. |
| C7 SIGTERM | 25 s under SIGTERM, 60 s for `finish()`/atexit, one env var. |
| C8, C9 | Fix both: `sys.exit(N)` with an open run is recorded failed/N; excepthook and atexit move to the first run open. |
| C10, C11 | Document both (no fsync; `VMN_WRITER_ID` or an exact `run_id` for fleets). |

**SDK shape (plan 41)**

| Item | Decision |
|---|---|
| D3 wheel contents | **(differs)** Move `registry/cli*`, `reports/` and `core/push_*` to vmn-exp. |
| D5-D11 API | Warn, then remove; `define_metric` raises on unknown keywords at once; `resolve_storage` is a thin SDK function. |
| D13-D15, D17 | Real GCS/Azure SDKs and signature parity now; emulators in CI before D13/D14 ship; D17 not started. |

**Server (plan 42)**

| Item | Decision |
|---|---|
| E1 / B5c argv | **(differs)** Uniform `--flag=value` for every option through one builder; the argv-pinning tests are rewritten. |
| E3 | Verify ID-token signatures: RS256 in the standard library behind a `JwksVerifier`, with a second reviewer. |
| E5a, E5b | Per-request roles and revoke-by-owner; no IdP re-check for now. |
| E7 | Document sticky routing; the client treats a 404 poll as unknown. |
| E12c2, E12e | Not yet: log first; typed models wait. |
| E14a / F15 | Web tests and ESLint are a blocking CI stage after a one-off fix pass. |

**Docs and release (plan 43)**

| Item | Decision |
|---|---|
| F1, F2 positioning | Measured facts with their cost; headline becomes "storage is the source of truth; training never depends on a server". |
| F5 `ui.md` | **(differs)** Split the HTTP API into its own file. |
| F10 changelog | Regenerated after upload. |
| F11 | Keep the `==` pin; promise that a server reads records from any older SDK of the same layout and record format. |
| F12 Python | **(differs)** Both packages `>=3.10`. |
| F13 | Small-store contract test and a "Solo impact" line in every plan from 37 on. |
| F14 roadmap | Build: LightGBM/CatBoost autolog, ASHA early stopping, notebook repr. Deferred: HTML/audio media, W&B importer, per-project permissions. Rejected: an HTTP logging endpoint. Declined: LLM/trace logging. Hosted stays a business decision. |

**IO (plan 44)**

| Item | Decision |
|---|---|
| G2 ports | Duplicated small Protocols in both packages with a parity test and shared fakes. |
| G7, G10 | Handlers take `io` explicitly; shims build the real one until plan 35 provides it. |
| G14 | `SnapshotStorage` is the filesystem interface; local storage implementations are exempt with a reason each. |
| G11 Part B, G17 | **(differs)** Both in plan 44: the status clock migration and the `core/index.py` split. |

### Applied

Plans 38-44 were reworked to these decisions on 2026-11-11: each file's Status
line says so, unchosen options and sign-off gates are gone, every named test
edit is listed in its item, and each file was re-checked against `59becdd5`
(26 upstream commits after the drafts). The rework dropped A11, B5c, C12, F15
and E10 (done upstream), parked D17, E7b, E5b, E12c2 and E12e, and added C15,
C16, F16, F17 and F18. The milestones, conflicts and invariants in this file
describe the reworked plans.

### Second round of owner answers (2026-11-11)

Taken while M0 and M1 were being implemented. They win over the list below and
over any item text that still says otherwise; items not yet started must be
read with these applied.

| Topic | Answer |
|---|---|
| Deprecations (F9, D5, D7, D9, D11) | **No deprecation period.** Old forms are removed or made errors at once, with no warning stage: positional `start_run` arguments, positional `app_name`/`ref` on `get_metric_history`, incomplete `list_runs` rows raise, the default `create_exclusive` is abstract. Everything ships together in one release, each change with an `upgrading.md` row. F9 keeps the row rule and the format ratchet and drops the removal distance. The `FutureWarning` question is moot. |
| Real-wired defaults (G4, G11) | **Required everywhere.** No fallback to the real clock or IO in `create_app`, `WorkspaceManager`, `ExperimentIndex`, `Run` and the other widely built names: every construction site passes its IO, about 1,200 edits, mostly in tests (approved). `derive_status` takes a required `now`. |
| A5 shipping | Per record copy is accepted; no storage change. The CLAUDE.md stream-owner line is reworded to say the owner is the record copy. |
| A5 guest stream | Named `<writer>-sdk~<owner>`. |
| C15 supervisor | After a signal, the child wait and the final upload together fit 25 s; the unsignalled path keeps the long budget. |
| CLAUDE.md | Three more edits approved: the stream-owner invariant (A5, C6), `reports` in the vmn-exp package list (D3), real IO in the index helper's `main()` (G11). |
| E5a old tokens | Kept; `upgrading.md` documents how to revoke. |
| E1 `prune` | The UI job action refuses `keep=0` (requires `keep >= 1`); the CLI is unchanged. |
| C16 failed UI edit | The next action on the workspace first retries the pending upload; the job result says the edit is pending until it ships. |
| F12 Python | Client job images are all on 3.10+: raise both floors now. |
| F16 autolog tests | Fakes first, plus lightgbm and catboost in the exp test requirements for one real test each. |
| Guard tests | A guard that cannot be red on arrival gets a deliberate-break check: break the code once, record the failing output, restore. |
| B7 | The no-repo path rejects stray positionals with exit 2 too. |
| E3 | RS256 only; other algorithms are refused with a clear error. |
| F5 / E13 | The model registry endpoint table lives in `ui-api.md`; `models.md` links to it. |

Still open after this round: the port shapes to agree with plan 35 (G2).

### Still open for the owner

Raised by the rework; none blocks M0 or M1 except where a line says so.

Release and process:

1. **F9** Confirm the removal distance for deprecations, proposed as 10 releases and 30 days. D5, D7, D9 and D11 step 2 wait on it.
2. **F12** Check the Python version of the client's job images (each run records `env.python`) before both packages require `>=3.10`.
3. **F10** Confirm that refactor, docs and test commits stay out of the changelog; the answer covered placement only.
4. **F13** Confirm the rule that a plan may carry a negative solo impact only with the trade-off stated and a setting that keeps the solo default.
5. **D5, D7** `FutureWarning` instead of `DeprecationWarning` (hidden by default outside `__main__`), so jobs print it; F9's text still says `DeprecationWarning`.
6. **CLAUDE.md** Three edits the plans need are not among the approved ones: the stream-owner invariant line (A5 at :229, C6 at :221), `reports` in the vmn-exp package list (D3), and a sentence allowing real IO in the index helper process's `main()` and the real-wired fallbacks (G11).
7. **Pinning tests** Tests that pass on arrival (budgets, ratchets, golden records, characterization tests) rely on a deliberate-break check; the TDD rule as written has no such exception.

First run and CLI:

8. **A5** Shipping is per record copy: on a shared local copy either process's sync uploads every stream the copy owns. Accept that, or add a storage item that selects by writer id.
9. **A5** `-sdk` as the guest stream suffix becomes a permanent object-name convention in every store.
10. **B7** Stray positional refs return 2 instead of 1 (a third behaviour change, beside the two named); and whether the no-repo path should reject them too.

SDK write path:

11. **C16** The premise was false: UI edit ships already run on a job thread. The item now pins that and bounds the job. Confirm that scope.
12. **C16** A UI edit whose ship failed stays in the server's buffer and is applied later, or twice if repeated. Drop it, ship it before the next action, or show its own status? Not planned.
13. **C15** `vmn-exp run` waits up to 30 s for the child and then up to 60 s for final uploads, so a pod with a 30 s grace period can be killed first. Shorter budget after a forwarded signal, or document raising the grace period (the plan's choice)?

Server:

14. **E3** Which algorithm the client's IdP signs ID tokens with (ES256-only or PS256-only breaks login on upgrade), and whether its discovery document has `jwks_uri`.
15. **E5a** Login tokens minted before the upgrade keep their stored roles for up to 90 days. Accept with a revoke-by-owner instruction, or invalidate every login token on upgrade?
16. **E1** `keep=0` stays legal over HTTP and deletes every run, as on the CLI; the 16 KiB note bound is a proposal.
17. **E13, F5** Whether the model registry endpoint table lives in `ui-api.md` or `models.md` after the split.

IO and roadmap:

18. **G4, G11** Widely built names (`ExperimentIndex`, `LeaderboardCache`, `SqliteStore`, `WorkspaceManager`, `create_app`, `open_storage`, `Refresher`, the three index functions) still resolve an omitted clock or IO to the real one, which CLAUDE.md forbids in new code. The alternative is about 1,200 construction-site edits no plan names.
19. **G11** `derive_status` with a required `now`: is an `upgrading.md` row enough, or does F9's deprecation window apply, since experiments.md names the call?
20. **G2** Port shapes to agree with plan 35 before either `ports.py` is written: `Clock.now()` as an aware UTC datetime, `Processes.popen`, `Host`, and whether `Processes.run` returns `None` or raises for a missing binary.
21. **F16** Whether to add lightgbm and catboost to the exp test requirements; without them the real-library tests skip.

Unknowns the implementer settles, recorded in each item's Risk, not owner
questions: whether `uv run`, `conda run` and Windows launchers exec or spawn
(A5); A10's verstr shape (its spike); whether flock excludes across hosts on a
network volume (C6); the Azure and GCS SDK facts (D13-D15); the web suite's
duration and failures today (E14a); how `uv lock` resolves mixed Python floors
(F12); which git calls are redundant (B9d, after the re-measure).

## Recommendations as put to the owner

The planners' original questions and recommendations, kept for the reasoning. The decisions above supersede them.

1. Plan doc numbering. Five streams claim docs/plans/36-*. Recommendation: 36 onboarding (A), 37 CLI (B), 38 SDK write path (C), 39 SDK shape (D), 40 server security/API (E), 41 docs and release (F), 42 roadmap gaps (F14), 43 vmn-exp IO (G); every one gets a README row, a Status line and a 'Solo impact:' line (F8, F13).
2. Test-edit policy (one decision instead of twelve). CLAUDE.md forbids editing a test to make a change pass without asking. Recommendation: (1) approve mechanical, constructor-arguments-only commits for classes built in a handful of test files (JobRunner, AuditLog, TokenService, StoreUpkeep, SettingsCache, Sampler, _Supervision); (2) for widely built names (create_app, WorkspaceManager, ExperimentIndex, LeaderboardCache, open_storage, Refresher, Run) keep the name as a real-wired factory and add the injected form beside it, no test edits; (3) decide individually the tests that pin behaviour being changed: test_exp_coldstart_detached.py:31 (A11), test_exp_rerun_cli.py:50-72 (A12), JobsKind.test.tsx:94-102 (A6), test_docs_similar_statements.py:80-86 anchor (B5d), test_ui_jobs.py argv pins and four siblings (E1 commit 2), OIDC fixtures with http issuers/unsigned tokens (E2, E3), test_ui_device_login.py:97-106 and test_ui_auth_oidc.py:88-110 (E5a), test_release_exp_script call list (F10), 22 test import repoints (D3), about 115 clock patch sites (G11 Part B), two paths in test_docs_similar_statements.py (F5 split).
3. CLAUDE.md amendments. A9, F3, F15, G3, G7 and G10 propose edits to CLAUDE.md (docs layout, Running Tests, and the list of entry points allowed to build real IO: plugin.py handler shims and the vmn_exp.sdk public functions). Only the owner can approve changes to CLAUDE.md. Recommendation: approve the docs-layout and test-lane lines; approve start_run/public SDK functions and the plugin shims as entry points, since a library has no main and vmn-exp has no hook into vmn_run until plan 35 lands.
4. Versioning thresholds and the breaking batch (F9, plus A5, B1, B5b, C7, C8, D8, E1, E2, E8 and the D5/D7/D9/D11 deprecations). Recommendation: stay on 0.x; minor for a store-layout or record-format change, a full-reload index upgrade, or a removed/changed documented interface; ship the behaviour-changing batch in one 0.2.0 with upgrading.md rows; deprecations introduced in 0.2.0 are removed in 0.3.0, not 0.2.0.
5. Changelog commit placement (F10). Recommendation: regenerate after upload (idempotent, cannot block a release); the tag does not contain its own changelog. Confirm refactor/docs/test commits stay out.
6. SDK/server compatibility promise and the == pin (F11). Recommendation: keep the pin; promise that a server/CLI reads records written by any older SDK of the same layout and record format, one golden record per format; no promise that an older server reads a newer SDK beyond 'unknown entries are ignored'.
7. Python floors (F12). Recommendation: vmn-exp >=3.9 now; vmn-exp-sdk stays >=3.8 only if someone runs its unit tests on 3.8 before each minor, otherwise >=3.9 at the next minor.
8. Web tests in CI: blocking or report-only (F15/E14a merged). Recommendation: blocking, after a one-off pass to fix whatever fails today; ESLint added as a second step with rules-of-hooks and exhaustive-deps as errors.
9. Adoption rule for `vmn-exp run` + start_run() (A5) and its scope (A12). Recommendation: direct-child rule, on by default, `--no-adopt` / VMN_EXP_ADOPT=0; the guest must write its own stream (see invariant_violations); extend to rerun and sweep trials only as a follow-up after A5 has been used. Not recommended: first-claimer-wins across the process tree.
10. CLI cold start pushing when a remote exists (A11). Recommendation: A1 alone now (no crash without a remote, push announced); change to never-push only after reading plan 17 F6, and keep pushing for CI first-runs if they matter.
11. Default view for an app with no outer runs (A6), and default baseline for an untracked-only run (B4c). Recommendation: decide A6 after looking at a post-A5 app in the Jobs table - if metrics show, skip it and add a 'declare a goal' hint instead; B4c: yes, prefer the run's own file list, the same rule a tracked patch follows.
12. Code-less run in a non-git directory/notebook (A10). Recommendation: yes, explicit opt-in only (`code=False` / VMN_EXP_CODE=none), never a fallback, after a verstr spike; record it as a row in the roadmap doc (F14).
13. `vmn-exp --version` format (B1). Recommendation: `vmn-exp <its version> (vmn <core version>)`.
14. Sorted `list` layout (B3). Recommendation: flat rows with `^[N]` / `^<verstr>` parent marker whenever rows are not in storage order.
15. Flags an action does not own (B5b) and per-action help (B5d). Recommendation: exit 2 from the release that carries the breaking batch (plan 32: no silent fallbacks); per-action help as help-only filtering, later, after approving the test anchor change; no real argparse subparsers.
16. UI job argv form (B5c/E1, one decision). Recommendation: validate every value and use `--note=<v>` only for a dash-leading note (no pinned test changes); the uniform `--flag=value` form only if the owner wants it and approves editing the argv-pinning tests.
17. `--json` scope (B6) and exit codes (B7). Recommendation: compare and comments only for now; stop at 0/1/2 plus the child's code.
18. Run overhead reduction (B9d). Recommendation: re-measure after A5; then (a) trim redundant git calls for every SDK run; (b) reusing the supervisor's code identity only if still needed and explicitly agreed.
19. Off-thread shipping scope (C3). Recommendation: the SDK-scoped hand-off to the run's existing gated sync worker; not a shipper thread inside BufferedRemoteStorage. Also decide who owns the same fix for the `vmn-exp run` supervisor and the UI server edit storage (currently nobody).
20. Log buffer location and recovery command (C5, C6). Recommendation: state dir or $VMN_EXP_CACHE_DIR with automatic local-temp fallback on network/unwritable homes; explicit `vmn-exp buffers list|ship`, no automatic recovery at start_run; ship only buffers whose owner lock can be taken (see invariant_violations).
21. SIGTERM finalize budget (C7). Recommendation: 25 s under SIGTERM, 60 s for finish()/atexit, one env var for both.
22. sys.exit(N) with an open run (C8) and import-time hooks (C9). Recommendation: wrap sys.exit from the first start_run and record failed/N; keep the SIGTERM handler at import but inert without open runs; move excepthook/atexit to the first Run._open and accept the exit-order flip.
23. Durability and .rN listing (C10, C11). Recommendation: document both (no fsync; VMN_WRITER_ID or run_id for fleets); no store-layout change.
24. SDK wheel contents (D3). Recommendation: keep index/similar/query/app_settings in the job wheel (D1/D2 make them free at import); do the registry/cli* move for the no-argparse rule and the reports/ move for a clean boundary; treat core/push_* as optional.
25. SDK API compatibility choices (D5, D7, D8, D9, D10, D11). Recommendation: positional start_run arguments warn, then removed one minor after the warning ships; deprecate positional app_name/ref on get_metric_history and update the docs that teach it; define_metric raises on unknown keywords immediately; list_runs keeps incomplete='warn' and flips to 'raise' one minor later; public resolver named `resolve_storage` as a thin SDK function (not an alias of the core function); default create_exclusive warns now and becomes abstract one minor later.
26. Storage contract: emulator CI stage (D15) and duck-typed storages (D17). Recommendation: stage 1 (real SDKs in test requirements, GCS signature parity) now; stage 2 (fake-gcs-server, Azurite) before D13/D14 ship, or defer all three if no client uses GCS/Azure; do not start D17 until a concrete cost appears.
27. OIDC signature verification (E3). Recommendation: RS256 in the standard library behind a JwksVerifier interface, with a second reviewer; PyJWT[crypto] as a later swap if other algorithms are needed.
28. Role freshness (E5b). Recommendation: ship E5a (roles derived per request, configurable TTLs, revoke-by-owner that also closes sessions); do the refresh-token re-check only if near-immediate deprovisioning is required.
29. Jobs across replicas (E7). Recommendation: document sticky routing and make the client treat a 404 poll as 'unknown'; persist jobs in the control plane only if replicas without sticky routing are a real deployment.
30. ValueError handler and typed API (E12c2, E12e). Recommendation: log first (E12c), narrow after one release of evidence; typed request/response models and generated types.ts not yet - revisit when vmn-exp is split out or a second client appears.
31. Positioning statements (F2). Recommendation: publish measured facts with their cost (737k runs on S3, memory, warm page times) linked to ui.md, reword PRODUCT.md principle 4 to 'thousands to hundreds of thousands of runs', and align docs/vmn-exp/architecture.md:351 ('even at 100k runs') with it.
32. ui.md split (F5). Recommendation: TOC only now; no split.
33. Solo-user protection (F13). Recommendation: a plan may carry a negative solo impact only with the trade-off written in its 'Solo impact' line and a setting that keeps the solo default.
34. Roadmap gaps (F14, nine rows plus A10). Recommendation: do LightGBM/CatBoost autolog, ASHA, HTML/audio media, notebook repr; keep HTTP ingest rejected; defer per-project permissions, video and the W&B importer; decline LLM tracing; hosted stays a business decision.
35. Where IO port definitions live (G2). Recommendation: duplicate the small Protocols in vmn_exp/core/ports.py and version_stamp/core/ports.py with a parity test and shared tests/fakes; plan 35 must adopt or reject three shape points (aware-datetime now(), Processes.popen, Host).
36. How vmn-exp CLI handlers get io (G7). Recommendation: handlers take io explicitly; the plugin.py shims build real_io() per invocation until plan 35 provides vmn_ctx.io.
37. SnapshotStorage as the filesystem interface (G14). Recommendation: yes; the local storage implementation modules are permanently exempt from the IO ratchet with a reason each.
38. Status clock migration (G11 Part B) and the core/index.py split (G17). Recommendation: approve Part B as one mechanical commit after G4/G7/G10 have shipped; split index.py in its own plan with benchmarks, not here.
39. Ratchet timing and bump rules (G1, G18, D1, D12). Recommendation: G1 at the start; G18 only at the start of the structural milestone; D1's import budget may be raised only in a commit that names the added module; D12's table is seeded after C3 so `defer_ships` is listed.

## Conflicts and ordering between workstreams

Found by reading the seven plans together, then re-checked after the rework.
Each names the resolution. Entries the decisions settled are gone: B5c against
E1, E14a against F15, the plan-doc numbers, the 0.2.0 batch, A6 against F13,
and the roadmap rows for A9 and A10.

1. TEXT DISAGREES - plan 39 B5b against plan 42 E1 on `--metrics`. 39-vmn-exp-cli-surface.md:292 says `--metrics k=v ...` is the one form E1 keeps. E1 emits one `--metrics=<k>=<v>` per metric and changes the parser line (cli/plugin.py:87-88) to `action="extend"`. E1 wins; fix the clause in plan 39 before B5b starts. The CLI change (a repeated `--metrics` accumulates) needs an experiments.md line and an `upgrading.md` row.
2. ORDERING - E1, B6, A4 and A12 before B5a/B5b. B5b rejects flags an action does not own (exit 2), so every flag the UI builder emits must be in B5a's ACTION_FLAGS: restore `--version`; prune `--keep`, `--older-than`; create `--note`, `--metrics`; add `--version`, `--note`, `--metrics`; tag `--remove`; rewind `--version`, `--step`; push `--version`. So must `--no-adopt` for run, rerun and sweep agent, and `--json` on compare and comments. B5b's UI-argv test walks the same action list as E1's fuzz test, so E1 exposes that list importably; E1's own test names stand. B5d's `action_parser(action)` must keep positionals-then-options working, because the UI builder depends on that order.
3. SAME FILE - cli/run.py `_Supervision`: A4, C15, B9b, A5, A12, G8. Order A4 -> C15 -> B9b -> A5 with A12 -> G8. A4 adds keyword-only `adopt`; C15 adds a required keyword-only `wait`, which changes the three constructions in test_exp_rerun_recording.py:140,155,165 (named in C15) and the callers in cli/rerun.py and cli/sweep/agent.py; A12 extracts those two call sites; A5 makes `_ingest`/`_finish` track the streams the supervisor appended to. G8 injects io into B9b's `watch()` and passes `io.env` as A4's base env, with `io` keyword-only.
4. SAME FILE, wide - sdk/run.py is edited by C1, C7, C4, C3, C9, C8, A5, D5, D6, A10, F18, G9, G10. Order C1 -> C7 -> C4 -> C3 -> C9 -> C8 -> A5 -> D5/D6 -> A10 -> F18 -> G9 -> G10. GuestRun overrides only `_publish`, `_publish_heartbeat`, `_record_final` and `_record_release`, so its overlap with C1/C7/G9 is those four. C1 passes LogSync its job as a callable defined in run.py, because tests patch `sync_to_remote` and `compact_by` on `vmn_exp.sdk.run`. Hook registration lives in C9's `process_hooks`; G9 leaves it there.
5. SAME FUNCTION - sdk/resume.py `locate()` and sdk/create.py: A3 (checkout guard), A5 (`action="adopt"`, which relies on create.py's re-entry guard), D6 (`from_env`, the hint when `action == "resume"`). Order A3 -> A5 -> D6. D6's hint must not fire for `action="adopt"`, and D5/D6 keep the re-entry guard reachable on the non-adopting path.
6. NEW SHARED FILES - core/writer.py and core/streams.py gain an optional `writer=` keyword in A5; plan 40's C chain and plan 44 G10/G12 touch their callers. A5 lands after the C chain and before G10.
7. SEMANTIC - A5 and A12 change what B9a's budget test "SDK start_run under vmn-exp run" measures: an adopted run goes through `resume.locate`, not `create_record`. Order B9a -> A5 with A12 -> B9d (re-measure, then trim). How a test grants adoption is A5's to define and B9d's to use.
8. SAME FILE - storage/buffered.py: C3 -> C13 -> C5 -> C6, then G10 (clock on the constructor and on C6's `reopen`) and G14 step 1 (its exempt list gains C5's storage/buffer_owner.py and C13's buffer_state.py). C16 does not touch this file. storage/cached.py: C1 adds `is_log_buffer`, which C15 uses to pick its recovery hint.
9. API vs IO PORTS - D10 and G10/G12. D10 ships `resolve_storage` as its own function in sdk/store_resolve.py, so G10 and G12 can add required `clock`/`env` to the core resolver and treat the SDK function as the place that builds the real ones. D10's behaviour test uses monkeypatch until G12 gives the core resolver an env parameter; G12 then rewrites it onto a fake env.
10. MODULE MOVES - D3 against C and G. C2 and C6 land before D3(c), and any test they add that imports `core.push_*` is repointed in D3 (15 test files at HEAD, all named). D3 lands before G11 Part A, G13 and G16, which already cite the post-move paths. D3(b) and G12 both edit core/storage_resolve.py; serialize them. G1 and G18 allowlists are regenerated in each D3 commit. D3's move list should gain C6's core/buffer_recover.py.
11. RATCHET vs PLANNED ADDITIONS - D1's import budget. Modules that land on the `start_run` import path: core/final_retry.py and sdk/log_sync.py (C1), exit_code (C8), process_hooks (C9), sdk/positional.py (D5), sdk/store_resolve.py (D10), core/ports.py and core/real_io.py (G2), sdk/run_records.py and sdk/run_close.py (G9), the six core/index_* mixins (G17), sdk/run_repr.py (F18). The FORBIDDEN-prefix test is the hard gate; the count may be raised only in a commit that names the added module. A3's checkout_guard, A5's adoption and guest_run, A10's codeless and F16's autolog_gbdt are imported inside the branch that needs them.
12. RATCHET vs PLANNED ADDITIONS - D12's probe table is seeded after C3 and C15. It gains one row, `defer_ships`, probed in sdk/run.py and cli/run.py.
13. RATCHET TIMING - G18 lands at the start of M5, after the C, A5 and E work, and must not cap sdk/run.py before A5 and F18 land. G1 lands at the start; every item that adds or removes a direct IO call after G1 updates `io_boundary_known.py` in the same commit. Known additions: `os.environ`/`os.getpid`/`os.getppid` reads (A4, A5), storage/buffer_owner.py and the host_dirs.py additions (C5), cli/supervisor_state.py (C15), ui/job_calls.py (C16), B1 and B9b. After G2 the same file lists who may call `real_io()`.
14. ORDERING - cli/experiment.py: B2, B3, B6, B5a, B5b and B7 before G15. B7 moves `refuse_stray_refs` to the top of `handle_experiment` beside B5b's check. G15 then moves what is left and reuses B's cli/compare_view.py and cli/list_layout.py.
15. SAME FILE - cli/plugin.py and cli/main.py: E1 (the `--metrics` line), A4 (`--no-adopt`), B1 (`run_argv(argv, read_version)` with `vmn_exp_run(argv)` as the wiring line), B5a (parser moves out), B8 (ui parser moves out), C6 (registers `buffers`), G7 (handler shims build `real_io()`; the version reader then comes from io). Order E1 -> A4 -> B1 -> B5a -> B8 -> C6 -> G7. `buffers` must be in B1's own-command list and epilog and in B7's exit-code table.
16. SAME FILE - ui/cli.py: E4 -> E2 -> E5a -> E3 -> B8 -> G7 -> G12 stage A -> G19.
17. SAME FILE - ui/server.py and ui/jobs.py. E9, E6, E12c, E12b, E12a and E5a add or change routes and handlers before G4 renames `create_app`'s body and G6 moves routes out behind a golden route table; the table is captured after E5a's `DELETE /api/v1/tokens?owner=`. E12c moves the ValueError handler to `api_errors.install`, so G6's list of what server.py keeps is re-read then. ui/jobs.py order: E1 -> E6 -> C16 -> G5; C16's `run_bounded` takes its thread starter as a parameter, which G5 injects. E5a changes the TokenService, SessionService and AuditLog constructors before G19 removes their clock defaults and G13 adds random; G19 re-takes its site counts after E5a and E3.
18. DOCS, same files.
    - docs/vmn-exp/README.md: F1 before A7 (A7 keeps F1's sentence and test); F3, F9, A9 and F5 add index links that F4 checks.
    - `upgrading.md`: created by F9; rows come from several dozen items across all seven plans. F9's tests ratchet only the Formats and Deprecations tables; a Behaviour row is each item's own duty.
    - `ui.md` and `ui-api.md`: F5 is one commit after re-grepping `ui\.md#`; any later API text (E12b, E12d, E13) targets `ui-api.md`. E1's Actions table (ui.md:146-159) is outside the API section and stays.
    - client-guide.md: A1, A8, F6, C5/C6 (the Kubernetes recipe mounts the cache dir on a ReadWriteOnce claim or hostPath), C11, D7.
    - experiments.md: A1, A5, B2/B3/B4a/B5b/B7, C2/C6/C7/C10/C11/C15, D11/D12, E1, F1, F5, F6, G11 Part B (:267). F6's anchor rename lands before the bulk of these or is re-checked by F4.
    - architecture.md: A5, D3, F2, F5, G17. vmn-vs-mlflow.md: F1, F2, F6, F14, F16.
    - cli/skill.py text changes (A4/A5 `--no-adopt`, B5b, B8, C6 `buffers`) regenerate docs/vmn-exp/agent-skill.md in the same commit.
19. RELEASE RULE - F9 against the deprecating items. F9 lands in M0, before any behaviour change. D5, D7, D9 and D11 take Deprecations rows and cite its removal rule; D8 and D3 take Behaviour rows; D10 takes neither. Two loose ends: the removal distance is proposed, not confirmed, and F9's rule text says `DeprecationWarning` where D5 and D7 use `FutureWarning`.
20. CORE VMN touched by vmn-exp streams. A2 (version_stamp/core/utils.py), B1 (cli/args.py, entry.py, plugin_api.py, api.py) and G2 (which may create version_stamp/core/ports.py if it lands before plan 35 stage 0) change core, and G7 waits for plan 35's `vmn_ctx.io`. Plan 35 owns core IO and is still proposed: whichever lands second rebases, and the port shapes are agreed first (open question 20).
21. ci/pipeline.py is edited by E14a (`tests_webui`), G3 (`tests_exp_unit`), D15 stage 2 (the emulator stage; `tests/run_pytest.sh` marker becomes `not serial and not emulator`) and F10 (release lane note). E14a and D15 put their stage tests in ci/test_pipeline.py; G3 still names packages/vmn-exp/tests/test_ci_pipeline_stages.py and should use ci/test_pipeline.py too. Any new cached test stage must declare outputs, or `test_test_stages_are_cached_on_the_sources_they_read` fails.
22. RECORD FORMAT - F11's golden record against A5 and A10. A5 changes no record format; it adds a stream-name pattern, `<writer>-sdk~<owner>`, which F11's golden record should include once A5 has shipped. A10's spike must say whether `RECORD_FORMAT_VERSION` changes, before F11 records the golden. F9's read-before-write rule for a format bump cannot be met while one constant serves writer and reader; that is a condition on a future bump.
23. cli/sweep/agent.py: A12 (trial call site, `--no-adopt`), C15 (`wait`), F17 (ASHA stopper), then plan 44 (the direct `time.monotonic()` at :134). Order A12 -> F17 -> G.
24. STATUS CALLERS - G11 Part B makes `now` required on `derive_status`, `status_fields` and `last_alive_at`. Status callers added earlier by A5 and B3 take `now` from their caller from the start, or G11's commit-3 ratchet test fails.

## Repo invariants the plans touch

Checked against CLAUDE.md and docs/vmn-exp/architecture.md, and re-checked
after the rework. The last entry lists what was checked and found consistent.

1. A5 and CLAUDE.md "only a stream's owner appends/ships/compacts it". Resolved for appending and compacting: the guest appends to its own stream, `<writer id>-sdk~<owner>`, and each process compacts only the streams it appended to; the invariant unit test is A5's first test. What remains is shipping. In the code the owner is the record copy, not a process, so on a shared local copy either process's sync uploads every stream the copy owns (storage/cached_logs.py:193-216, cached_metrics.py:179-203). That satisfies the rule as the code defines owner, but not "the guest never ships the supervisor's". Open question 8.
2. A5/A4 and the docs that describe nesting. architecture.md "The life of a run" (235-239) and "Outer runs and inner runs" (270-273), and CLAUDE.md's "`VMN_EXPERIMENT_ID` set in the environment auto-parents any new run" (:229), change with A5: the supervisor's direct child adopts instead of nesting. A5 now lists all of them, with the new CLAUDE.md wording; that line is not among the approved CLAUDE.md edits (open question 6).
3. C6 and the same invariant. Resolved by the lock rule: `buffers ship` takes the buffer's owner lock first, and a live owner's buffer is listed but never opened, shipped or removed. Shipping a dead owner's buffer is an exception that C6 writes into CLAUDE.md:221 and experiments.md:1833; the CLAUDE.md line needs approval (open question 6).
4. IO rule and new-code sites. The approved CLAUDE.md bullet makes `start_run`, the public SDK functions and the plugin.py handler shims entry points that may build real IO (G7, G10). B1 was reworked to comply (`run_argv` takes a required reader), and C8/C9 take `sys` and `atexit` from `start_run`. Still reading IO directly, and so listed in G1's allowlist in the same commit: A4/A5 (environment and pid reads), C5 (host_dirs, buffer_owner: env, tempfile, pid, flock), B9b until G8. G11 also builds real IO in the index helper process's `main()`, which the approved bullet does not name (open question 6).
5. G4/G11 and "don't hide a real implementation in a default argument in new code". The widely built names keep a real-wired form when the clock or IO is omitted. It is enforced by a REAL_WIRED allowlist and a test that production always passes the clock, but it is the same hiding one level up, and the owner has not accepted it (open question 18).
6. TDD "a new behavior's first test is a unit test that uses fakes". Resolved in the rework: A12, A4, B5b, B9a, C15, C16, D15 stage 2, E2, E9, E12a, E12d and E13 now start with a unit test on fakes. D15's emulator runs and F10's scoping test are real-IO by nature.
7. TDD "the test must fail for the right reason (red)". Several items add tests that pass on arrival: B9a (budget bounds), C10, C14 (if the resume path already works), D12's ratchet, F11 (golden record), F13 (solo-store contract), A5's storage-pinning test, the G1/G18 ratchets and the G6/G9/G15/G17 characterization tests. For refactors CLAUDE.md allows keep-green; for the others the plans rely on a deliberate-break check. Open question 7.
8. "Never edit a test to force a passing result". Decided: every test edit named in plans 38-44 is approved, and the reworked items name theirs (for example D3's 15 import repoints, F10's call list, G11 Part B's 119 patch sites, G19's roughly 80 constructor sites, E1's six argv files). An edit a plan does not name still stops and asks; C15 says so for the three supervisor tests that patch `LocalSnapshotStorage.save_file`.
9. File-size rule (about 200-300 lines per file). Items still add code to files far over it: A5 and F18 (sdk/run.py, 889 lines), B2/B5b/B7 (cli/experiment.py, 1227), E6/E9/E12a (ui/server.py, 839). Most new logic goes to new small modules (guest_run, adoption, job_argv, supervisor_state, run_repr), and M5 splits all four files, G17 included. sdk/run.py still lands near 550 lines after G9.
10. Models routes and "never add per-request store listing". E10 is done upstream: the list is served from a background snapshot. `ModelListing.with_model` still does one `list_files` of one model inside each mutating request, and GET .../models/{name} still reads the store per request. Neither has an item.
11. E9b's risk note and the same invariant: if an lstat/realpath check is needed in the index reader's worker processes, it is applied when a record is folded (refresh time), never per request.
12. D3 and the package lists. D3 now lists the exact edits to CLAUDE.md:78-81, architecture.md:91/98, docs/packaging.md and test_packaging_split.py. The CLAUDE.md edit needs approval (open question 6). The namespace rule (no `vmn_exp/__init__.py`) is respected: cli/pushing/ and cli/exp_parser/ are below the namespace root.
13. Docs-layout rule "CLAUDE.md Docs Layout lists every vmn-exp doc". New docs: notebooks.md (A9), vmn-vs-wandb.md (F3), ui-api.md (F5), upgrading.md (F9); each item plans its CLAUDE.md line, and those lines are approved. packages/vmn-exp/CHANGELOG.md (F10) is generated and never hand-edited.
14. No contradiction found (checked): status stays derived, never stored (the guest writes no state; C2, C13 and C15 publish run_state, not status); read-only actions take no repo lock (`buffers list`, B5b's pre-dispatch check); run verstrs are still claimed with `create_exclusive` (A10 must keep this for its code-less verstr); per-host state stays outside the store (C5); store layout v2 and `RECORD_FORMAT_VERSION` are unchanged (A5 adds only a stream name); SDK import rules hold (G2's ports are stdlib-only, B1 reaches core through `version_stamp.api`, D3 moves code out of the SDK wheel, not into it); core docs carry no experiment material; CI stays the local Muster pipeline (E14a, G3 and D15 add stages to ci/pipeline.py).

## Review findings only partly covered

What stays open if every item ships as planned, and why. Findings the rework
closed are gone: the supervisor's silent final sync (now C15), the missing
roadmap features (F16-F18), the `core/index.py` split (G17), the `ui.md` length
(F5), the architecture.md scale wording (F2) and per-action help (B5d).

1. C-write-path, inline remote PUTs: C3 moves them off the appending thread for SDK runs, C15 for the supervisor, and C16 pins the UI server. Still inline: a caller passing a raw remote store as `start_run(storage=...)` (LogBuffer's 1000-entry flush stays on the caller's thread). A UI edit whose ship failed is applied late or twice (open question 12).
2. C-write-path, a SIGKILLed pod's buffer: C5 and C6 make it discoverable and shippable, and the Kubernetes recipe now mounts the cache dir on a volume. A pod without a volume still has nothing to recover.
3. D-sdk-shape, reader and server logic in the SDK package: D3 moves `reports/`, `registry/cli*` and `core/push_*` (about 1.9k of 43k lines). `index*`, `similar*`, `query*`, app_settings, alerts/sinks, panel_spec and index_io_process stay in the job wheel, because the SDK's reader API imports them; D1 and D2 make them free at import.
4. E-server, models: GET .../models/{name} reads the store per request, and comment threads are one store read per request. No item.
5. E-server, no API schema: only E12e addresses the missing models and the hand-maintained types.ts, and it is parked. E12a-E12d fix the symptoms (500s, envelope, logging, parameter modes).
6. E-server, no JS end-to-end tests: a non-goal in plan 42. Vitest and ESLint in CI (E14a), the vendor chunk (E14b) and the StampTree split (E14c) are planned.
7. E-server, token growth: one 90-day token per `vmn-exp login`, never swept. E11 adds paging only.
8. F-docs, experiments.md is 2,116 lines: F6 renames commands and nothing shortens it.
9. F-docs, feature gaps: HTML/audio media, the W&B importer and per-project permissions are deferred with no item; HTTP ingest is rejected; LLM tracing is declined.
10. G-io-debt, direct IO: G14 step 2 (the FileSystem port) waits for plan 35's MemFS, and the real-wired forms keep a real default (open question 18). About 35 other files over 300 lines are capped by G18 only.
11. B-cli, `--json` on `settings`: deliberately not planned (`settings show` prints YAML). Covered: compare and comments (B6).
12. A-onboarding, the dashboard for simple runs: A5, A12 and A6 fix new runs. Wrapper-plus-child pairs recorded before A5 keep the old view, and the "(no goal)" hint to declare a goal metric has no item.
13. Follow-up with no item: delete ui/thread_limiters.py and its test once `anyio>=4.15` can be the floor, which F12 makes possible.
