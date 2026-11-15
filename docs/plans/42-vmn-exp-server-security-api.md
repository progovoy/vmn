# Plan 42: vmn-exp review fixes, server security, authorization and HTTP API

> Workstream E of the 2026-11-11 vmn-exp product review. The index, the
> milestone order, the cross-stream conflicts and the owner decisions are in
> [37-vmn-exp-review-fixes.md](37-vmn-exp-review-fixes.md). Each item was drafted by a
> planner that read the code, then revised by a critic that re-checked the
> evidence and looked for tests pinning today's behaviour.
>
> Sizes: S under a day, M 1-3 days, L about a week, XL more. Priorities: P0 security or data loss, P1 blocks adoption or misleads users, P2 quality, P3 nice to have.

Status: **proposed** (2026-11-11). Owner decisions of 2026-11-11 are applied in this file.

Solo impact: see each item's risk line; nothing here may make the single-user case worse.

## Summary

Critic pass over the draft: every cited file was opened in the main checkout. The findings are real, but several approaches were changed. The draft had 19 items and the critic pass 23. After the owner decisions and a re-read at master 59becdd5 (26 commits after the drafting commit 25f03f3d) the plan has 19 items to build, 4 parked and 1 dropped. Paths: ui/ = packages/vmn-exp/src/vmn_exp/ui/, sdk = packages/vmn-exp-sdk/src/vmn_exp/, web = packages/vmn-exp/webui, tests = packages/vmn-exp/tests/.

What the owner decisions changed:
- E1 uses the attached `--flag=value` form for every option, through one builder module (ui/job_argv.py). The tests that pin today's argv are rewritten (approved). It absorbs plan 39's B5c. `--metrics` becomes repeatable in the parser so each metric is one `--metrics=<k>=<v>` token.
- E3 is decided: verify ID-token signatures, RS256 in the standard library behind a `JwksVerifier` interface with injected http and clock, and a second reviewer on the crypto code.
- E5a ships (per-request roles, configurable lifetimes, revoke-by-owner that also closes sessions). E5b is parked.
- E7 is decided: document sticky routing and make the web client treat a 404 poll as unknown. Persisting jobs is parked as E7b.
- E12c2 and E12e are parked ("not yet"). E12c's logging ships.
- E14a and plan 43's F15 are one item, kept here as E14a: a blocking CI stage for the web unit tests after a one-off fix pass, then ESLint with rules-of-hooks and exhaustive-deps as errors. F15 points here.
- E13's endpoint-table test reads the HTTP API doc that plan 43 F5 splits out of ui.md (docs/vmn-exp/ui-api.md), through one file constant.
- Releases stay 0.1.x patch releases. Every behaviour change below names its `upgrading.md` row (the file is created by plan 43 F9) and gets a changelog entry.
- Test edits named in this file are approved. A test edit that is not named here still stops and asks.

What the code move changed (25f03f3d..59becdd5):
- E10 is done upstream: the Models list is served from a background-refreshed registry snapshot (8951f280), a write through the server re-reads only its model (c796563f), and the lineage and list snapshots share one registry listing per refresh (2d3374a4). E10 is under "Dropped". Its optional paging moved into E11.
- ui/server.py grew by 5 lines (834 to 839); line references are corrected. ui/jobs.py and the ui/auth/ files are unchanged since the critic pass (the `_metric_args` fix 859da19b was already counted).
- list_experiments gained `job_agg_nested` (fe3b0e12): it has 24 query parameters, and routes_leaderboard.py is 350 lines (E12d).
- docs/vmn-exp/ui.md grew by 60 lines; the API section now starts at :837 (E13).
- The web suite is 530 test files (49 of them in src/__tests__), not 527 (E14a).

What the critic pass had already changed (still true):
- The _metric_args fix has already landed (commit 859da19b), so E1 builds on it instead of rebasing.
- E1's premise was too generous. argparse does take some '-'-leading tokens as values: negative numbers ('--keep -1', pinned by tests/test_exp_rewind_cli.py:112 for --step) and any token with a space. So prune keep=-1 is a live bug, not only a latent one.
- E9 covered only two of the server's local read paths. Output tail and range reads also join names under the record dir; E9b enumerates and closes those.
- E6 missed multi tenancy: workspace names are per org, so a job must record its org too.
- E8 no longer guards every path: a Host check on '/' would 403 Kubernetes probes of a token-less read-only server. It guards /api, /metrics and /auth only.
- E12a no longer introduces Pydantic with extra='forbid' across 18 handlers (a breaking style change the finding does not need). It is a hostile-body sweep plus fixes in the existing hand-validator style.
- E5a also closes browser sessions on revoke-by-owner; the draft revoked tokens only.
- Priorities: E2 P0 -> P1 (a misconfiguration guard, not exploitable as shipped), E3 P1 -> P2 (defence in depth once E2 holds), E7 P2 -> P3.

Suggested order: E9, E1, E6, E4, E2, E5a, E9b, E14a, E8, E12c, E12b, E12a, E13 (after plan 43 F5), E3, E11, E12d, E14b, E14c, E7. E4, E2, E5a and E3 all edit ui/cli.py and land in that order. E14a comes before the first item that edits the web client (E12b), so those edits run under the web stage. Parked, not to be started: E7b, E5b, E12c2, E12e.

Not verified: no test suite was run. The parser behaviour E1 relies on was checked in-process (see E1 Evidence). Raise sites for E12c2, the bodies that 500 today (E12a), and the full list of symlink-following read paths (E9b) are to be enumerated by each item's first failing test. tests/test_uiload_browser.py uses Playwright by grep only. The web suite's duration and its failures today are unknown (E14a).

## Items

| Id | Pri | Size | Item | Owner decision |
|---|---|---|---|---|
| [E9](#e9) | P0 | S | Artifact download and table routes must not follow symlinks out of the run's record dir |  |
| [E9b](#e9b) | P1 | M | Enumerate and close the other server reads that follow symlinks in a local record dir |  |
| [E1](#e1) | P1 | M | One argv builder for UI job commands, every option as `--flag=value`, with a fuzz test over every action | decided |
| [E6](#e6) | P1 | S | Scope GET /jobs/{id} to the job's workspace and org |  |
| [E2](#e2) | P1 | S | OIDC: refuse non-https issuer and endpoints, and do not follow redirects |  |
| [E4](#e4) | P1 | S | Let an OIDC-configured server bind beyond localhost without a static token |  |
| [E5a](#e5a) | P1 | M | Roles: derive from groups at request time, configurable lifetimes, revoke one user's credentials and sessions | decided |
| [E14a](#e14a) | P1 | M | Web: the vitest suite as a blocking CI stage, then ESLint (also plan 43 F15) | decided |
| [E8](#e8) | P2 | S | Apply the Host and cross-site guards to /metrics and /auth, not only /api |  |
| [E13](#e13) | P2 | S | The HTTP API doc's endpoint table lists every route, checked by a test | decided |
| [E12c](#e12c) | P2 | S | Log every ValueError the global handler turns into a 400 |  |
| [E12b](#e12b) | P2 | S | One error envelope: every JSON error carries detail and code |  |
| [E12a](#e12a) | P2 | M | Wrong-typed request bodies answer 400/422, never 500 |  |
| [E3](#e3) | P2 | M | OIDC: verify the id_token signature against the IdP's JWKS | decided |
| [E11](#e11) | P3 | S | Optional paging for the reports, tokens and models lists |  |
| [E12d](#e12d) | P3 | M | list_experiments: group its 24 query parameters into validated modes |  |
| [E14b](#e14b) | P3 | S | Web: split vendor code out of the 572 KB entry chunk, with a size budget |  |
| [E14c](#e14c) | P3 | M | Web: split pages/StampTree.tsx (749 lines) |  |
| [E7](#e7) | P3 | S | Job polls across replicas: document sticky routing, a 404 poll reads as unknown | decided |
| [E7b](#e7b) | parked | M | Persist jobs in the control plane | decided |
| [E5b](#e5b) | parked | L | Roles: periodic re-check with the IdP (refresh token) | decided |
| [E12c2](#e12c2) | parked | M | Narrow the ValueError handler to named client errors | decided |
| [E12e](#e12e) | parked | XL | Typed request and response models, and a generated types.ts | decided |

<a id="e9"></a>
### E9. Artifact download and table routes must not follow symlinks out of the run's record dir

P0 · S

**Problem.** Confirmed. artifact_local_path validates only the name, joins it under the record dir and tests os.path.isfile, which follows symlinks. download_artifact serves the result with FileResponse and load_table opens it. within() exists but only static_files.py calls it. Anyone who can write into a run's artifacts/ or outputs/ tree in a file:// store or git workspace (any job on a shared filesystem) can plant a symlink to a file the server user can read (server.yml, the control-plane SQLite file, /proc/self/environ with the static token or OIDC client secret), and any viewer can then download it.

**Approach.**

UI-side containment (not in the SDK: a user who symlinks a large checkpoint into artifacts/ and reads it back job-side keeps working). New pure helper contained_artifact_path(storage, app_name, verstr, name) in ui/security.py: returns storage.artifact_local_path(...) only when storage.local_record_dir(...) is not None and within(record_dir, path); else None. For backends whose local_record_dir is None (S3 cache path, sdk/storage/s3.py:155-185) it returns the path unchanged, since that file was downloaded by the server itself. A backend with open_artifact is streamed before the local path is consulted (server.py:538-551) and is not affected. server.download_artifact and routes_media.load_table call the helper. A refused path answers the same 404 as a missing file. cli/report_export.py:37 runs as the CLI user on their own machine and is left alone.

**Tests first.**

- tests/test_ui_security_paths.py (new, pure; written first): test_contained_artifact_path_refuses_a_path_outside_the_record_dir, test_contained_artifact_path_returns_a_path_inside_it, test_contained_artifact_path_passes_through_when_backend_has_no_record_dir (a fake storage object whose local_record_dir and artifact_local_path return chosen paths under tmp_path)
- tests/test_fix_ui_security.py: test_artifact_symlink_leaving_record_dir_is_404 (file:// store under tmp_path, os.symlink to a file outside; no git repo)
- tests/test_fix_ui_security.py: test_artifact_under_symlinked_parent_dir_is_404
- tests/test_fix_ui_security.py: test_symlink_inside_record_dir_is_still_served
- tests/test_fix_ui_security.py: test_table_symlink_leaving_record_dir_is_404
- tests/test_fix_ui_nested_artifacts.py stays green unchanged

**Files.** `packages/vmn-exp/src/vmn_exp/ui/security.py`, `packages/vmn-exp/src/vmn_exp/ui/server.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_media.py`, `docs/vmn-exp/ui.md`, `docs/vmn-exp/upgrading.md (row)`

**Risk.** A store laid out by hand with artifacts symlinked to another volume stops serving them through the UI (job-side SDK reads are unaffected). Document in ui.md; the change needs an upgrading.md row (per plan 43 F9). realpath costs a few lstat calls per download; the route is not hot.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/storage/base.py:252-258 (artifact_local_path: name check + isfile)`; `packages/vmn-exp-sdk/src/vmn_exp/storage/files.py:84-89,106-108 (valid_artifact_path; artifact_file_path is a plain join)`; `packages/vmn-exp-sdk/src/vmn_exp/storage/local.py:383-385 (local_record_dir)`; `packages/vmn-exp/src/vmn_exp/ui/server.py:524-555 (download_artifact; 538-551 open_artifact stream, 552-555 artifact_local_path, isfile, FileResponse(path))`; `packages/vmn-exp/src/vmn_exp/ui/routes_media.py:62-69 (load_table opens the path)`; `packages/vmn-exp/src/vmn_exp/ui/security.py:136-143 (within)`; `packages/vmn-exp/src/vmn_exp/ui/static_files.py:17,62 (only caller of within)`; `packages/vmn-exp-sdk/src/vmn_exp/storage/local.py:380 (artifacts are written with shutil.copy2; grep found no symlink creation in sdk src)`

<a id="e9b"></a>
### E9b. Enumerate and close the other server reads that follow symlinks in a local record dir

P1 · M · depends on E9

**Problem.** E9 covers named downloads only. Other server reads also join a name under the record dir and open it: LocalSnapshotStorage.read_file_from, and the failed-run output tail (the last 40 lines of outputs/output.log, shown on the run page). A planted outputs/output.log symlink would show the tail of any text file the server can read. The list-artifacts walk also reports a symlink target's existence and size. The draft did not cover these; I confirmed the join sites but not every route that reaches them.

**Approach.**

Test first, as the enumeration: one parametrized test builds a file:// store under tmp_path, replaces each kind of record file the UI serves with a symlink to an outside file holding a marker string (outputs/output.log, a media image, a histogram or table document, a log segment, metadata.yml), requests every read route of create_app for that run, and asserts the marker appears in no response body. Then fix what fails at the narrowest shared point: the UI wraps a local storage for serving in a small reader (beside ui/readers/listed_reads.py, which already wraps read_range/read_file_from) that refuses a name whose realpath leaves the record dir, and list_artifacts results are filtered through the same check. No SDK behaviour change.

**Tests first.**

- tests/test_fix_ui_security_symlinks.py (new; the enumeration, written first): test_no_read_route_serves_a_symlink_target_outside_the_record_dir (parametrized over record-file kinds; tmp_path file store, TestClient; no git repo, no Docker)
- tests/test_ui_contained_reads.py (new, pure; the first test of the fix): test_contained_reader_refuses_outside_realpath_and_delegates_inside (fake storage)
- tests/test_fix_ui_security_symlinks.py: test_artifact_listing_omits_symlinks_leaving_the_record_dir

**Files.** `packages/vmn-exp/src/vmn_exp/ui/readers/contained_reads.py (new, under 100 lines)`, `packages/vmn-exp/src/vmn_exp/ui/server.py (wrap where the serving storage is built)`, `packages/vmn-exp/src/vmn_exp/ui/readers/failure_context.py`, `docs/vmn-exp/ui.md`

**Risk.** The index's worker processes read record dirs directly (local.py:281-287 plain_record_dir) and fold symlinked log files into the index; whether that leaks through list rows is something the first test decides. If it does, the fix may need an lstat check in the index reader, which is a hot path: measure before adding realpath there.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/storage/local.py:277-279 (read_file_from: os.path.join, no containment)`; `packages/vmn-exp/src/vmn_exp/ui/readers/failure_context.py:23,64 (output_tail of outputs/output.log)`; `packages/vmn-exp/src/vmn_exp/ui/readers/listed_reads.py:24-38 (ListedReads already wraps read_range/read_file_from)`; `packages/vmn-exp-sdk/src/vmn_exp/storage/files.py:111-122 (list_artifact_tree: os.path.isfile/getsize follow links)`; `docs/vmn-exp/ui.md:1676 (output_tail: one range read of at most 16 KB)`

<a id="e1"></a>
### E1. One argv builder for UI job commands, every option as `--flag=value`, with a fuzz test over every action

P1 · M · absorbs plan 39 B5c · lands before plan 39 B5a/B5b

**Problem.** build_command turns HTTP body strings into vmn / vmn-exp argv. The vmn-exp side is one flat parser carrying every action's options (--attach, -o/--output, -f/--file, --tool, --remove ...), so a value parsed as an option would reach options the action never meant to expose. Older actions pass raw values as their own argv tokens with no validator: stamp --pr, release -v, restore -v, goto -v, prune --keep/--older-than, exp_create/exp_add/note --note and -v. The belief that argparse rejects every '-'-leading value is wrong in two cases: a negative-number token is accepted as a value (tests/test_exp_rewind_cli.py:112 shows '--step -1' reaching the handler), and a token containing a space is always a value. So POST .../actions/prune with keep=-1 becomes '--keep -1' and prune.py:78 deletes metas[:1], the oldest run, instead of refusing; keep=-5 deletes the five oldest. A bare '--' token also cuts the command line, because the experiment command is registered with split_after_double_dash. Values may be non-strings too (a list for prerelease lands in argv).

**Approach.**

One builder module, one form. Every option that carries a value is emitted as the single token `<long flag>=<value>`; a value can then never be read as a flag, whatever it starts with.

New pure module ui/job_argv.py (under 100 lines), functions only:
- `opt(flag, value)` returns `f"{flag}={value}"`. It refuses a flag that is not in the module's `LONG_FLAGS` tuple and a value that is not a `str`.
- `positional(value)` returns the value, or raises for a non-str, an empty string or a '-'-leading one (this also refuses a bare `--`).
- `switch(flag)` returns a boolean flag from the fixed `SWITCHES` tuple (`--dry-run`).
- `EMITTED = {action: (long flags...)}` is the table below as data. build_command dispatches on one `ACTIONS` tuple, and `EMITTED` has exactly those keys.

build_command (ui/jobs.py) and the four builders in ui/jobs_exp_meta.py build every request-derived token through `opt` / `positional`; nothing else appends to an argv. Subcommand words stay literals.

Token order is part of the contract. For a `vmn-exp experiment <action>` command the positionals come directly after the action word and every option after them, as today (`experiment restore my_app --version=1.0.0`). The experiment parser's `action` positional is `nargs="?"` (cli/plugin.py:60-61), so an option placed between the action word and the app makes argparse read the action word as the app name: `experiment prune --keep=5 my_app` parses to action `create`, name `prune`, refs `['my_app']`. The core commands (`stamp`, `release`, `goto`) keep today's order, options first and the app last; both orders parse there. bulk_actions.commands() reuses exp_tag_command and exp_archive_command and changes with them.

What each action emits (the short forms `-r` and `-v` are no longer used):

| Action | Command | Options | Positionals |
|---|---|---|---|
| stamp | `vmn stamp` | `--release-mode=<mode>`, `--pr=<prerelease>`, `--dry-run` | app |
| release | `vmn release` | `--version=<verstr>` | app |
| goto | `vmn goto` | `--version=<verstr>` | app |
| restore | `vmn-exp experiment restore` | `--version=<verstr>` | app |
| prune | `vmn-exp experiment prune` | `--keep=<n>` or `--older-than=<d>` | app |
| exp_create | `vmn-exp experiment create` | `--note=<text>`, one `--metrics=<k>=<v>` per metric | app |
| exp_add | `vmn-exp experiment add` | `--version=<verstr>`, `--note=<text>`, one `--metrics=<k>=<v>` per metric | app |
| note | `vmn-exp experiment add` | `--version=<verstr>`, `--note=<text>` | app |
| exp_tag | `vmn-exp experiment tag` | one `--remove=<key>` per key | app, verstr, `k=v` pairs |
| exp_rewind | `vmn-exp experiment rewind` | `--version=<verstr>`, `--step=<n>` | app |
| exp_push | `vmn-exp experiment push` | one `--version=<verstr>` per run | app |
| exp_archive, exp_unarchive | `vmn-exp experiment archive` / `unarchive` | none | app, verstrs |

Multi-value options, one by one:
- `--version` on the experiment parser and `--remove` are `action="append"`: repeated `--version=<v>` / `--remove=<k>` tokens accumulate today. No parser change.
- `--metrics` is `nargs="*"` with the default store action (cli/plugin.py:87-88). In the attached form it takes exactly one value, a second `--metrics=` replaces the first, and a following bare `k=v` token lands in `refs`. So the parser line gains `action="extend"`: `--metrics=a=1 --metrics=b=2` then gives `['a=1', 'b=2']`, and the terminal form `--metrics a=1 b=2` still parses as today. This is the only parser change in E1 and it is its own first commit with its own test. Side effect for CLI users: a repeated `--metrics` flag now adds to the earlier one instead of replacing it.
- Tag `k=v` pairs and archive verstrs are positionals (`refs`, nargs="*"), not options. They go through `positional()` after the existing validators, which already refuse a leading '-'.
- The core options (`--release-mode`, `--pr`, `--version` on release and goto) are single-value store options and need no change. Nothing in core vmn is edited.

Field validators run before the builder and answer the 400:
- verstr: `_valid_verstr` for release, restore, goto, exp_add and note (today only tag, archive, rewind and push use it).
- prerelease: a non-empty printable `str`.
- keep: an `int` >= 0 and not a `bool`. older_than: `^\d+[dwh]$`, which is what prune._parse_duration accepts.
- note: a `str` of bounded length (proposed 16 KiB; one argv string is limited by the OS). A note may start with '-' ('- lowered lr'); it is one token, `--note=- lowered lr`.
- metric names: the existing `_metric_args` check. Metric values: a number (not a bool) or a string; a list or dict is refused.
- release_mode: the existing choice check.

The job's `command` (shown in the UI and returned by the API) changes form: `["vmn", "stamp", "--release-mode=minor", "--pr=rc", "my_app"]`. The web's client-side CLI hints (web/src/pages/Actions.tsx:98-99, NoteEditor.tsx, NewExperiment.tsx) stay in the form a person types.

Plan 39 B5b: once `foreign_flags` and `ACTION_FLAGS` exist, B5b must own every flag in `EMITTED` for its action, or UI jobs start failing with exit 2. The exp rows of the table above are the list: restore `--version`; prune `--keep`, `--older-than`; create `--note`, `--metrics`; add `--version`, `--note`, `--metrics`; tag `--remove`; rewind `--version`, `--step`; push `--version`. B5b adds the assertion "`foreign_flags` is empty for every action's benign argv" to E1's fuzz file. stamp, release and goto are core vmn commands and outside B5b's table. Flags that other streams add to actions the UI runs (`--no-adopt`, `--json`) are not emitted by this builder.

Two commits: (1) `--metrics` becomes `action="extend"`; (2) job_argv.py, the validators, the uniform form and the test rewrites together.

**Tests first.**

All in-process, no subprocess, no repo.

- tests/test_exp_metrics_flag_repeats.py (new; argparse only): test_repeated_attached_metrics_accumulate, test_space_separated_metrics_still_parse, test_attached_and_separate_forms_mix. Red today: the second `--metrics=` replaces the first.
- tests/test_ui_job_argv.py (new, pure): test_opt_renders_one_token, test_opt_refuses_non_str_value, test_opt_refuses_unknown_flag, test_positional_refuses_dash_leading_empty_and_non_str, test_note_starting_with_dash_is_one_token, test_emitted_table_covers_every_action
- tests/test_ui_job_argv_fuzz.py (new): test_no_body_field_can_set_another_dest. For every action in ACTIONS and every body field (and list element, dict key and dict value), substitute each of `['-x', '--attach=/etc/passwd', '--', '-v', '--note=x', '-1', '-1 x', ['-x'], {'a': 1}, 7, True]`. Assert build_command returns an error, or that parsing `argv[1:]` yields a namespace equal to the benign-body namespace except the one intended dest. The benign-body namespace itself must carry the intended command, action word and app name (this is what fails when an option is put before the app). Parsing uses version_stamp.cli.args.parse_user_commands after `vmn_exp.cli.plugin.register_all()` (the `vmn.plugins` entry point registers only the dev-version loader, so `experiment` is unknown to the parser until register_all has run).
- tests/test_ui_job_argv_fuzz.py: test_exp_actions_put_the_app_before_every_option (for each vmn-exp action, the token after the action word is the app and no positional follows an option), test_every_action_is_fuzzed (ACTIONS against the fuzz table), test_every_emitted_option_is_one_token_with_an_equals_sign (no argv token after the subcommand words starts with '-' unless it is `--flag=...` or a SWITCHES member), test_every_emitted_flag_is_a_long_option_of_its_parser
- tests/test_ui_jobs.py: test_ui_prune_keep_must_be_non_negative_int (keep=-1, '-1', True, '5 --dry-run'), test_ui_prune_older_than_must_be_a_duration, test_ui_release_goto_restore_refuse_invalid_verstr, test_ui_stamp_prerelease_must_be_str

Existing tests rewritten to the new argv (approved; expected lists change, nothing else):
- tests/test_ui_jobs.py:143-144 (`"-r" in job["command"]` becomes `"--release-mode=minor" in job["command"]`), :147-170 (exp_create), :178-196 (note), :198-220 (exp_add), :293-308 (goto)
- tests/test_fix_ui_jobs_tags.py:10-24 (`"--remove", "old"` becomes `"--remove=old"`)
- tests/test_ui_jobs_push.py:16-19
- tests/test_ui_jobs_rewind.py:9-12
- tests/test_ui_jobs_metric_names.py:37-46 (`["--metrics", "val-loss=0.1"]` becomes `["--metrics=val-loss=0.1"]`; `["--metrics", "delta=-1", "flag=--attach"]` becomes two attached tokens)
- tests/test_ui_jobs_bulk.py:48-56 (the tag commands of a bulk job; the earlier drafts did not list this file)

The archive tests (test_fix_ui_jobs_tags.py:74-78) pin positionals only and stay unchanged.

**Files.** `packages/vmn-exp/src/vmn_exp/ui/job_argv.py (new)`, `packages/vmn-exp/src/vmn_exp/ui/jobs.py`, `packages/vmn-exp/src/vmn_exp/ui/jobs_exp_meta.py`, `packages/vmn-exp/src/vmn_exp/cli/plugin.py (the --metrics line only)`, `packages/vmn-exp/tests/test_ui_job_argv.py (new)`, `packages/vmn-exp/tests/test_ui_job_argv_fuzz.py (new)`, `packages/vmn-exp/tests/test_exp_metrics_flag_repeats.py (new)`, the six test files listed above, `docs/vmn-exp/ui.md (Actions table at :146-159: field rules and the command form)`, `docs/vmn-exp/experiments.md (--metrics is repeatable)`, `docs/vmn-exp/upgrading.md (row)`

**Risk.** Requests accepted today with odd values (keep as a string, a verstr with a slash, a list as prerelease) become 400, and API clients that read a job's `command` see the attached form: the change needs an upgrading.md row (per plan 43 F9) and a changelog entry. A repeated `--metrics` on the command line now accumulates; that goes in the same row. jobs.py is 319 lines; moving the validators and builders out brings it under 300. Store workspaces do not build an argv (ui/jobs_store.py runs their actions in-process), so their body checks are E12a's, not this item's. Plan 39 B5a moves the experiment parser out of cli/plugin.py; E1 lands first so the `--metrics` line moves with it. Not settled by reading: whether any web test renders a real job `command` from the server rather than a fixture; the web suite (E14a) will show it.

**Owner decision (2026-11-11).** Uniform `--flag=value` for every option through one builder module, with the fuzz test over every action and every body field. The argv-pinning tests are rewritten. This item replaces plan 39's B5c.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/jobs.py:75-175 (build_command; 85-87 -r and --pr, 94-96 release -v, 100-104 restore, 106-112 goto, 114-122 prune with str(body['keep']), 124-131 exp_create, 133-146 exp_add, 148-161 note)`; `packages/vmn-exp/src/vmn_exp/ui/jobs.py:55-72 (_metric_args with the landed '-' check; renders '--metrics' then k=v tokens)`; `packages/vmn-exp/src/vmn_exp/ui/jobs_exp_meta.py:15-38 (validators), 54-57 (--remove as two tokens), 67, 79 (positionals), 89-90 (-v, --step), 98-100 (-v per run)`; `packages/vmn-exp/src/vmn_exp/ui/bulk_actions.py:78-91 (commands() reuses the tag and archive builders)`; `packages/vmn-exp/src/vmn_exp/cli/plugin.py:48-253 (one pexp parser), 66 (refs nargs='*'), 74 (--remove append), 78 (-v/--version append), 84 (--note), 87-88 (--metrics nargs='*'), 108-110 (--keep type=int, --older-than), 225-226 (--step type=int), 501-517 (register_all; split_after_double_dash=True)`; `packages/vmn/src/version_stamp/cli/args.py:23-53 ('--' split), 193-199 (release -v/--version), 227-229 (goto -v/--version), 259-261 (stamp -r/--release-mode), 275-277 (--pr/--prerelease)`; `packages/vmn-exp/src/vmn_exp/cli/prune.py:58-67 (_parse_duration), 75-79 (_candidates: metas[:-keep])`; `packages/vmn-exp/src/vmn_exp/ui/server.py:584-602 (run_action feeds body to build_command)`; `packages/vmn-exp/src/vmn_exp/ui/auth/authz.py:19 (prune needs admin)`; `packages/vmn-exp/tests/test_exp_rewind_cli.py:112`; `checked in-process at 59becdd5 (parse_user_commands after register_all, Python 3.12): '--release-mode=patch --pr=rc', 'release --version=1.0.0', 'goto --version=1.0.0', 'restore --version=', '--keep=5', '--older-than=30d', '--note=- lowered lr', '--note=--', '--remove=old --remove=-x' (both kept), '--version=a --version=b' (both kept), '--step=3' all parse to the intended dest; '--keep=-1' parses to -1 (the validator must refuse it); '--metrics=loss=0.3 --metrics=acc=0.9' keeps only acc; '--metrics=loss=0.3 acc=0.9' puts acc=0.9 in refs; a plain argparse parser with nargs='*', action='extend' accumulates both forms; re-checked by the checker on the same commit: 'experiment restore my_app --version=1.0.0' gives action restore, while 'experiment restore --version=1.0.0 my_app', 'experiment prune --keep=5 my_app', 'experiment rewind --version=1.0.0 --step=3 my_app' and 'experiment push --version=a my_app' all give action 'create' with the action word as the app name`

<a id="e6"></a>
### E6. Scope GET /jobs/{id} to the job's workspace and org

P1 · S

**Problem.** The job route has no workspace in its path, so require(VIEWER) passes for anyone holding any role anywhere: a viewer of workspace A can read the command and log of a job run in workspace B given its id. Job records neither its workspace nor its org. Ids are uuid4 hex, so this needs a leaked id, but logs can hold paths, remotes and tool output. In multi tenancy workspace names are per org (vmn_workspaces is an RLS table), so a check by workspace name alone would still let org X read org Y's job in a same-named workspace.

**Approach.**

Job gains workspace (set in JobRunner._start from its existing workspace_name argument) and org_id (passed by the three server call sites, server.py:599, 644 and 660, from request.state.org_id; 0 in single tenancy). Neither is added to to_dict. JobRunner.get_scoped(job_id) returns (job_dict, workspace, org_id). get_job takes Request and answers the same 404 'Job not found' unless the principal's org matches and authz.allowed(principal, job.workspace, VIEWER, role_mappings); with auth disabled it behaves as today. 404 rather than 403 so an id cannot be confirmed. URL and payload unchanged; the web client is untouched.

**Tests first.**

- tests/test_ui_jobs_scope.py (new; JobRunner with a submit_call job, no subprocess): test_job_records_workspace_and_org
- tests/test_ui_authz.py: test_job_of_other_workspace_is_404_for_scoped_viewer, test_job_visible_to_viewer_of_its_workspace, test_job_visible_to_star_admin, test_job_visible_without_auth, test_job_of_other_org_is_404_in_same_named_workspace

**Files.** `packages/vmn-exp/src/vmn_exp/ui/jobs.py`, `packages/vmn-exp/src/vmn_exp/ui/server.py`

**Risk.** A token scoped to one workspace that polled another workspace's job now gets 404; that is the fix, and it needs an upgrading.md row (per plan 43 F9). tests/test_fix_ui_security_jobs.py (24-57) builds Jobs directly and must keep passing: the new fields get defaults.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/server.py:666-671 (get_job: require(VIEWER), no ws)`; `packages/vmn-exp/src/vmn_exp/ui/auth/authz.py:37-41,66 (workspace None + VIEWER = any role anywhere)`; `packages/vmn-exp/src/vmn_exp/ui/jobs.py:178-198 (Job has no workspace), 230-257 (submit* know workspace_name), 279-290 (_start)`; `packages/vmn-exp/src/vmn_exp/ui/tenancy.py:20-24 (vmn_workspaces under row-level security)`; `packages/vmn-exp/src/vmn_exp/ui/auth/principal.py:32 (Principal.org_id)`

<a id="e2"></a>
### E2. OIDC: refuse non-https issuer and endpoints, and do not follow redirects

P1 · S

**Problem.** The id_token signature is skipped on the documented ground that it arrives in the token endpoint's direct TLS response (OIDC Core 3.1.3.7 allows this only then). Nothing enforces TLS: config accepts any issuer string, discovery is fetched from it as given, and token_endpoint / device_authorization_endpoint from the discovery document are used unchecked. UrllibHttp uses urlopen, which follows redirects including https to http. An http issuer, or a discovery document naming an http token endpoint, lets a network attacker hand the server an unsigned id_token with any groups, and therefore any role.

**Approach.**

Pure helper require_https(url, what) in ui/auth/oidc.py raising OIDCError unless the scheme is https, or http with a loopback host (a local IdP in development). Called (1) from config._auth for auth.oidc.issuer, as a ConfigError at start-up, (2) in OIDCAuthenticator.metadata() for authorization_endpoint, token_endpoint and device_authorization_endpoint (and jwks_uri after E3), before the document is cached. cli._oidc_chain applies it to server.public_url (the session cookie is Secure and the redirect URI carries the code). UrllibHttp builds an opener whose redirect handler refuses every redirect; that thin real implementation gets one test against a loopback http.server. No escape-hatch flag.

**Tests first.**

- tests/test_ui_oidc_https.py (new, pure; written first): test_require_https_accepts_https, test_require_https_accepts_loopback_http, test_require_https_refuses_http_and_other_schemes
- tests/test_ui_auth_oidc.py: test_discovery_with_http_token_endpoint_is_refused, test_discovery_with_http_authorization_endpoint_is_refused, test_loopback_http_issuer_is_allowed (the file's FakeIdP at :29 is the fake)
- tests/test_ui_device_login.py: test_device_start_refuses_http_device_endpoint (FakeDeviceIdP at :24)
- tests/test_ui_config.py: test_oidc_issuer_must_be_https, test_public_url_must_be_https_with_oidc
- tests/test_ui_oidc_http.py (new; real-IO test of the thin implementation, loopback server): test_redirect_is_refused

**Files.** `packages/vmn-exp/src/vmn_exp/ui/auth/oidc.py`, `packages/vmn-exp/src/vmn_exp/ui/auth/oidc_http.py`, `packages/vmn-exp/src/vmn_exp/ui/config.py`, `packages/vmn-exp/src/vmn_exp/ui/cli.py`, `docs/vmn-exp/server.md`, `docs/vmn-exp/upgrading.md (row)`

**Risk.** A deployment with a plain-http IdP on a private network, or an http public_url behind a TLS-terminating proxy that was configured as http, stops starting; the error names the key and the loopback exception. The change needs an upgrading.md row (per plan 43 F9). Existing fixtures were checked and need no edit: tests/test_ui_auth_oidc.py:17 uses ISSUER = "https://idp.example" with an https redirect URI, and the config fixtures use https issuers and public_url (test_ui_server_config.py:13,20, test_ui_role_mappings_config.py:22,26, test_ui_workspace_registry.py:104,106). test_ui_server_config.py:77 uses `issuer: a` in a config that must already be refused for its unknown key; it stays a refusal.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/auth/oidc.py:1-9 (rationale), 51-56 (jwt_claims: base64 decode only), 81-90 (metadata(): only issuer equality), 124-128 (token endpoint used as discovered), 131-143 (checked_claims)`; `packages/vmn-exp/src/vmn_exp/ui/auth/device.py:37-42,77-80`; `packages/vmn-exp/src/vmn_exp/ui/config.py:45-50,148-159 (OIDCSection: no issuer validation)`; `packages/vmn-exp/src/vmn_exp/ui/auth/oidc_http.py:11-27 (urlopen of any URL, default redirect handling)`; `packages/vmn-exp/src/vmn_exp/ui/cli.py:148-166 (_oidc_chain: public_url required, scheme unchecked)`

<a id="e4"></a>
### E4. Let an OIDC-configured server bind beyond localhost without a static token

P1 · S

**Problem.** handle_ui refuses a non-loopback bind unless a static token is set (or --read-only), and looks at nothing else. A server whose auth is OIDC must therefore also carry a shared static secret, and that secret is an admin in every workspace. Operators are pushed into keeping a break-glass credential they did not ask for. The warning at 294-298 has the same blind spot.

**Approach.**

Extract a pure function bind_refusal(host, has_token, has_oidc, read_only) -> ('error'|'warning', message) or None in ui/cli.py and use it in handle_ui (has_oidc = cfg is not None and cfg.auth.oidc is not None). A non-loopback bind is allowed when a static token or auth.oidc is configured. A control plane alone does not count: API tokens cannot be minted without a first admin. The refusal text lists the three ways out (token, auth.oidc, --read-only). server.md states that the static token is an all-workspace admin and is optional once OIDC is configured, and that an OIDC-only server needs at least one role_mappings entry granting admin on '*' or nobody can administer it.

**Tests first.**

- tests/test_ui_cli.py: test_bind_refusal_none_for_oidc_without_token, test_bind_refused_with_control_plane_only, test_bind_refused_without_any_auth, test_read_only_bind_without_auth_warns, test_loopback_never_refused (pure function, no server start)

**Files.** `packages/vmn-exp/src/vmn_exp/ui/cli.py`, `docs/vmn-exp/server.md`, `docs/vmn-exp/ui.md`

**Risk.** Only loosens a start-up refusal in a case that is authenticated. tests/test_ui_cli.py:154-173 (test_ui_refuses_non_loopback_without_token_or_read_only, test_ui_starts_read_write_when_safely_configured) pin today's behaviour for the token and read-only cases and stay green; the refusal message gains a third option, so check the asserted substrings ('--read-only' at :162) still appear.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/cli.py:284-298 (both checks read only 'token')`; `packages/vmn-exp/src/vmn_exp/ui/cli.py:148-166,180 (_oidc_chain built later, from cfg.auth.oidc)`; `packages/vmn-exp/src/vmn_exp/ui/auth/static.py:6 (STATIC_PRINCIPAL = admin on '*')`; `packages/vmn-exp/src/vmn_exp/ui/server.py:174-182 (chain; auth_enabled = bool(chain); a control plane alone adds ApiTokenAuthenticator)`; `docs/vmn-exp/server.md:425 (static token acts as admin in every workspace)`

<a id="e5a"></a>
### E5a. Roles: derive from groups at request time, configurable lifetimes, revoke one user's credentials and sessions

P1 · M

**Problem.** principal_for computes roles from groups at login and stores them in the session (12 h, persisted in the control plane across restarts) and in the device-flow API token (90 days). After a role mapping is removed from server.yml and the server restarted, or after a user leaves a group, the stored role still applies until expiry: authz already recomputes mapped roles from principal.groups per request, but the frozen copy in principal.roles is merged in with stronger(). Device tokens do not carry groups at all, so they can only be frozen. An admin cannot cut off one user short of finding each token id, and has no way to close that user's browser sessions.

**Approach.**

(1) OIDC principals carry groups only: principal_for returns roles={}; authz derives roles from groups and app.state.role_mappings on each request (effective_role already does). OIDCConfig.role_mappings becomes unused and is removed, with the line in cli._oidc_chain that fills it. (2) TokenRecord gains groups (default ()); it is a JSON doc, so records without the field still load. DeviceFlow.poll mints with roles={} and groups=principal.groups; TokenService.create takes groups; verify returns them on the Principal. Tokens minted before the change keep their stored roles until expiry (documented). Admin-created API tokens are unchanged: explicit roles, by design. (3) auth.oidc.session_ttl_hours (default 12) and auth.oidc.login_token_ttl_days (default 90) in OIDCSection, validated positive, passed from cli._oidc_chain to SessionService and DeviceFlow (both already take ttl_sec). (4) DELETE /api/v1/tokens?owner=<principal id> (admin on '*') revokes every token of that owner and closes that principal's sessions: TokenService.revoke_owner and SessionService.close_principal. The control plane's `list(kind)` returns the documents without their keys (control_plane.py:188-191, control_plane_pg.py:77-82) and a session's key is the hash of its cookie value, so today a session document cannot be deleted from a listing. SessionService.open therefore stores the key inside the document (`session_key`), SessionService.principal removes it before building the Principal, and close_principal lists the 'session' documents and deletes by `session_key` those whose stored `id` matches. No control-plane interface or migration change. The route answers `{"tokens": n, "sessions": m}`. (4b) SessionService.principal returns the Principal with roles={}: only the OIDC login opens sessions (oidc.py:129), so a session opened before the upgrade loses its frozen roles at once and is judged by its groups like a new one. (5) server.md states the remaining lag: an IdP group change is seen at the next login, bounded by the two TTLs; revoke-by-owner is the tool for an urgent removal. No re-check with the IdP (that is E5b, parked).

**Tests first.**

All on the in-memory or tmp_path SQLite control plane with a fake clock; no IdP, no network.

- tests/test_ui_authz.py: test_removed_role_mapping_drops_role_of_live_session, test_oidc_principal_has_no_stored_roles, test_login_token_role_follows_current_mappings
- tests/test_ui_device_login.py: test_login_token_carries_groups_not_roles, test_login_token_ttl_from_config
- tests/test_ui_auth_tokens.py: test_revoke_owner_revokes_all_of_that_owner_only, test_record_without_groups_field_still_loads, test_admin_created_token_keeps_explicit_roles
- tests/test_ui_auth_sessions.py (new): test_close_principal_closes_only_that_principals_sessions, test_session_ttl_from_config, test_session_key_is_stored_and_not_passed_to_the_principal, test_close_principal_leaves_a_session_stored_without_its_key, test_stored_session_roles_are_ignored (a session document written in the old shape, with roles and no session_key)
- tests/test_ui_token_api.py: test_delete_tokens_by_owner_is_admin_only, test_delete_tokens_by_owner_closes_sessions
- tests/test_ui_config.py: test_oidc_ttls_validated_positive

Existing tests rewritten (approved; they pin the frozen-roles behaviour this item removes):
- tests/test_ui_device_login.py:97-106 test_token_carries_the_mapped_roles: it asserts `principal.roles == {"ml": EDITOR}` on the verified token. It becomes test_login_token_carries_groups_not_roles (roles == {}, groups == ("ml-team",)) plus an authz assertion that the same principal is an editor in `ml` under the mappings. The `role_mappings=` argument at :60 goes away with the OIDCConfig field.
- tests/test_ui_auth_oidc.py:67-110: `_client` passes `role_mappings` to OIDCConfig (:76-79) and its `_whoami` probe returns `p.roles` (:85-88); test_login_flow_sets_session_and_principal asserts `"roles": {"ml": EDITOR}` (:110). The fixture sets `app.state.role_mappings` instead, and the probe returns the effective role per workspace through authz.effective_role.

**Files.** `packages/vmn-exp/src/vmn_exp/ui/auth/oidc.py`, `packages/vmn-exp/src/vmn_exp/ui/auth/device.py`, `packages/vmn-exp/src/vmn_exp/ui/auth/tokens.py`, `packages/vmn-exp/src/vmn_exp/ui/auth/sessions.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_admin.py`, `packages/vmn-exp/src/vmn_exp/ui/config.py`, `packages/vmn-exp/src/vmn_exp/ui/cli.py`, `docs/vmn-exp/server.md`, `docs/vmn-exp/upgrading.md (row)`

**Risk.** A user whose role came only from a mapping that has since been removed loses it on upgrade, at once instead of at expiry, in browser sessions and in login tokens minted after the upgrade; that is the fix, and it needs an upgrading.md row (per plan 43 F9). Two leftovers go in the same row: a login token minted before the upgrade keeps its stored roles until it expires (up to 90 days) and cannot be told apart from an admin-created token, and a session opened before the upgrade has no stored key, so revoke-by-owner cannot close it (it expires within 12 hours). The row tells the admin to run revoke-by-owner for anyone whose mapping was removed, and that such a user's old browser session lasts at most the remaining session lifetime. Under multi tenancy the session list in close_principal must run inside the caller's org context like the other session calls. SessionService, TokenService and OIDCAuthenticator default clock=time.time; pass the clock explicitly from cli._oidc_chain in the code touched here (IO rule for touched code). Plan 44 G19 removes those defaults later and must come after this item. The new route changes the route table: plan 44 G6 captures its golden route list after E5a.

**Owner decision (2026-11-11).** Ship E5a as described: roles per request, configurable lifetimes, revoke-by-owner that also closes sessions. No IdP re-check for now (E5b is parked).

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/auth/oidc.py:39 (OIDCConfig.role_mappings), 145-149 (principal_for stores roles and groups)`; `packages/vmn-exp/src/vmn_exp/ui/auth/device.py:16,69-75 (90-day token minted with principal.roles)`; `packages/vmn-exp/src/vmn_exp/ui/auth/sessions.py:11,19,24-32 (12 h session stores asdict(principal); ttl_sec is a constructor parameter)`; `packages/vmn-exp/src/vmn_exp/ui/auth/authz.py:22-41 (effective_role merges principal.roles with roles_for_groups(principal.groups, mappings); allowed)`; `packages/vmn-exp/src/vmn_exp/ui/auth/tokens.py:25-34,59-64,89 (TokenRecord has roles and owner, no groups; create; revoke by id)`; `packages/vmn-exp/src/vmn_exp/ui/routes_admin.py:41-60 (list, revoke by id only)`; `packages/vmn-exp/src/vmn_exp/ui/control_plane.py:92-103 (list, page, count, scan by kind), 183-191 (delete by key; list selects doc only)`; `packages/vmn-exp/src/vmn_exp/ui/control_plane_pg.py:72-82 (the same two in Postgres)`; `packages/vmn-exp/src/vmn_exp/ui/auth/sessions.py:34-43 (principal: Principal(**doc))`; `packages/vmn-exp/src/vmn_exp/ui/auth/oidc.py:129 (the only sessions.open call)`; `packages/vmn-exp/src/vmn_exp/ui/cli.py:148-166,202 (role_mappings read once at start, into OIDCConfig and app.state)`; `packages/vmn-exp/src/vmn_exp/ui/shell_meta.py:40-44,64 and request_author.py:30 (role display already goes through effective_role)`; `packages/vmn-exp/tests/test_ui_device_login.py:60,97-106`; `packages/vmn-exp/tests/test_ui_auth_oidc.py:67-110`

<a id="e8"></a>
### E8. Apply the Host and cross-site guards to /metrics and /auth, not only /api

P2 · S

**Problem.** RequestGuard.reject_reason returns early for any path not starting with /api. /metrics (run names, counts, rollup gauges) is therefore reachable through DNS rebinding on a token-less localhost server, and POSTs to /auth/* skip the cross-site check. With auth on, /metrics is still protected by require(VIEWER), so this is the no-auth case only; the /auth part is low impact because the session cookie is SameSite=Lax.

**Approach.**

Replace the '/api' test with a GUARDED_PREFIXES tuple ('/api', '/metrics', '/auth'): Host allowlist and cross-site mutation checks run for all three; the JSON content-type rule stays /api-only (logout posts no body). The static bundle and SPA shell stay unguarded on purpose: they hold no data, and a Host check on '/' would answer 403 to Kubernetes probes and load-balancer health checks that hit a token-less read-only server by pod IP (the draft's every-path version had that regression).

**Tests first.**

- tests/test_ui_request_guard.py (new, pure: RequestGuard.build + reject_reason, no app): test_metrics_refuses_unknown_host_without_token, test_metrics_allowed_with_token_any_host, test_cross_site_post_to_auth_logout_refused, test_logout_without_content_type_allowed, test_spa_paths_stay_unguarded
- tests/test_fix_ui_security.py: test_metrics_403_for_rebound_host (TestClient, one end-to-end check)

**Files.** `packages/vmn-exp/src/vmn_exp/ui/security.py`, `docs/vmn-exp/ui.md`, `docs/vmn-exp/server.md`, `docs/vmn-exp/upgrading.md (row)`

**Risk.** A Prometheus scraper hitting a token-less server by pod IP now gets 403 on /metrics until the host is passed with --allowed-host (bind_host is allowed already unless it is a wildcard). The change needs an upgrading.md row (per plan 43 F9) and a changelog entry. tests/test_ui_cache_api.py:88 scrapes /metrics through TestClient, whose host is allowlisted (security.py:80), so it stays green.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/security.py:94-106 (early return at 96-97)`; `packages/vmn-exp/src/vmn_exp/ui/routes_cache.py:35-38 (/metrics outside the API prefix, require(VIEWER))`; `packages/vmn-exp/src/vmn_exp/ui/server.py:236-256 (401 only for /api paths; guard middleware)`; `packages/vmn-exp/src/vmn_exp/ui/auth/oidc_routes.py:48-69 (POST /auth/logout, /auth/device/*; cookie samesite=lax at :44)`; `packages/vmn-exp/src/vmn_exp/ui/static_files.py:55-66 (SPA shell and bundle on every other path)`

<a id="e13"></a>
### E13. The HTTP API doc's endpoint table lists every route, checked by a test

P2 · S · after plan 43 F5

**Problem.** The endpoint table omits routes that exist: GET .../apps/{app}/search, .../apps/{app}/events, .../experiments/{verstr}/outputs/{path}, .../experiments/{verstr}/summary and .../failures (the last four appear only in prose). Nothing keeps the table in step with the code.

**Approach.**

Plan 43 F5 moves the HTTP API section (ui.md "## API", from :837 today) into its own file, docs/vmn-exp/ui-api.md. E13 lands after F5 and checks that file. The test names the file once, as a module constant `ENDPOINT_DOC = "docs/vmn-exp/ui-api.md"`, and finds the table by its header row (`| Method | Path |`), not by a line number or a heading.

Test first: build create_app over a tmp_path manager (plus one app built with a fake OIDC chain and an in-memory control plane so /auth/* and the token/audit routes exist), list every route (method + path, parameter names normalised to the doc's {ws}/{app}/{verstr} spelling), and assert each appears in a table row of ENDPOINT_DOC or of the doc a small delegation map in the test names for its prefix (models.md, reports.md, server.md). The reverse check fails on rows naming a route that no longer exists. The comparison itself is a pure function `undocumented(routes, table_rows)` with its own unit test on hand-made lists. Then add the missing rows; the failing test names any omissions beyond the five known.

If E13 has to start before F5 lands, the constant points at docs/vmn-exp/ui.md and F5's move commit changes that one line (an approved test edit).

**Tests first.**

- tests/test_docs_ui_endpoints.py (new): test_undocumented_names_a_route_missing_from_the_rows, test_undocumented_ignores_parameter_spelling (pure, hand-made lists)
- tests/test_docs_ui_endpoints.py: test_every_route_is_documented, test_documented_routes_exist (create_app over tmp_path, the real doc file)

**Files.** `docs/vmn-exp/ui-api.md (created by plan 43 F5)`, `packages/vmn-exp/tests/test_docs_ui_endpoints.py (new)`

**Risk.** Docs only. From then on a route without a docs row fails the suite, which is the intent; diag routes (diag.install_app) are either documented or listed as an explicit exclusion in the test. E5a adds DELETE /api/v1/tokens?owner= and E11 adds parameters, so whichever lands second adds its row. The model registry routes have their own table in the API section (ui.md:1934-1940 today); the delegation map decides whether that table or models.md is their home once F5 has moved them.

**Owner decision (2026-11-11).** Plan 43 F5 was decided as a real split of the HTTP API into docs/vmn-exp/ui-api.md, so this test reads the new file through one constant and E13 is ordered after F5.

**Evidence.** `docs/vmn-exp/ui.md:837 (## API), 843-844 (table head); 588, 591, 1022, 1046, 1816 (prose-only mentions of summary, events, failures, outputs); 1934-1940 (model registry table)`; `packages/vmn-exp/src/vmn_exp/ui/routes_run_search.py:28`; `packages/vmn-exp/src/vmn_exp/ui/routes_events.py:45`; `packages/vmn-exp/src/vmn_exp/ui/routes_job.py:51,58`; `packages/vmn-exp/src/vmn_exp/ui/server.py:559-571 (one download route per FILE_TREES entry)`; `packages/vmn-exp/src/vmn_exp/ui/auth/oidc_routes.py:21-62 and routes_cache.py:35 (routes outside /api/v1 that also need a documented home)`

<a id="e12c"></a>
### E12c. Log every ValueError the global handler turns into a 400

P2 · S

**Problem.** A global handler maps any ValueError raised under a request to 400 with str(exc). It exists so storage's refusal of a bad path component is a client error, but it also relabels real server bugs (int('x') in a reader, a failed unpack) as the caller's fault with no log line and no stack, so they are invisible to the operator.

**Approach.**

Move the handler into api_errors.install and make it log at warning with exc_info and the method and path (through the logger server_logging already configures) before answering the same 400. Behaviour for clients is unchanged. The log shows which raise sites actually reach the handler; that is the evidence the parked E12c2 would need.

**Tests first.**

- tests/test_ui_api_errors.py (new): test_value_error_is_400_and_logged_with_stack (a tiny FastAPI app with api_errors.install and a route raising ValueError; caplog), test_storage_bad_component_still_400

**Files.** `packages/vmn-exp/src/vmn_exp/ui/api_errors.py`, `packages/vmn-exp/src/vmn_exp/ui/server.py`

**Risk.** Log volume if a client hammers a bad path: one warning per request. Acceptable; rate-limit only if it shows up.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/server.py:262-265 (the handler), 267 (api_errors.install)`; `packages/vmn-exp/src/vmn_exp/ui/auth/principal.py:12-17 (check_roles raises ValueError; caught at routes_admin.py:52-53)`; `packages/vmn-exp/src/vmn_exp/ui/routes_media.py:102-105 and routes_models.py:117-119,130-131,145-146 (routes that already catch ValueError themselves)`

<a id="e12b"></a>
### E12b. One error envelope: every JSON error carries detail and code

P2 · S · depends on E12c

**Problem.** Error bodies come in four server shapes: {detail} (HTTPException and the guard), {detail, code} (CodedError), {detail, reason} (diff, tree, events) and {detail, auth} (401). Clients must branch on which key exists.

**Approach.**

api_errors.install registers an HTTPException handler that adds code when missing, from a small status table (400 bad_request, 401 unauthorized, 403 forbidden, 404 not_found, 409 conflict, 415 unsupported_media_type, 422 invalid_body, 429 busy, 503 unavailable). The {detail, reason} sites and the two middleware JSONResponses go through one helper error_body(detail, code, **extra) that emits code and keeps reason (same value) and auth as extra keys. Purely additive. The HTTP API doc (docs/vmn-exp/ui-api.md after plan 43 F5, ui.md before) gets one 'Errors' paragraph listing the codes. The device-flow {error} body stays (RFC 8628, see refuted).

**Tests first.**

- tests/test_ui_api_errors.py: test_plain_http_exception_has_code, test_coded_error_code_wins, test_error_body_keeps_extra_keys (pure)
- tests/test_ui_api_errors.py: test_reason_sites_also_carry_code, test_401_keeps_auth_hints_and_has_code, test_guard_403_has_code (TestClient over a tmp_path manager)

**Files.** `packages/vmn-exp/src/vmn_exp/ui/api_errors.py`, `packages/vmn-exp/src/vmn_exp/ui/server.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_tree.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_events.py`, `packages/vmn-exp/src/vmn_exp/ui/static_files.py`, `packages/vmn-exp/webui/src/http.ts (read code first, reason as fallback)`, `docs/vmn-exp/ui-api.md (ui.md before plan 43 F5)`

**Risk.** Additive keys only. A grep for exact-dict assertions found one file, tests/test_ui_ref_error_codes.py, which already expects code; any other test comparing a whole error body is found by running the suite; it is not named here, so editing it stops and asks.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/api_errors.py:12-31 ({detail, code})`; `packages/vmn-exp/src/vmn_exp/ui/server.py:242-243 ({detail, auth}), 253-255 (guard {detail}), 698-702 ({detail, reason})`; `packages/vmn-exp/src/vmn_exp/ui/routes_tree.py:17 and routes_events.py:50,55 ({detail, reason}; cited by the draft, not re-read by me)`; `packages/vmn-exp/src/vmn_exp/ui/static_files.py:33-34 (unknown /api path {detail})`

<a id="e12a"></a>
### E12a. Wrong-typed request bodies answer 400/422, never 500

P2 · M · depends on E1, E12b

**Problem.** 18 handlers take body: dict and index into it by hand; there are no request models. A field of the wrong type reaches library code: add_workspace passes body['name'] of any type to the manager; comment reply_to and anchor go to the store unchecked; device/token passes any device_code type into a string concat (device.py:58). These surface as 500s or as jobs failing with a TypeError.

**Approach.**

Step 1 is the sweep test: enumerate every POST/PUT/PATCH/DELETE route of create_app, send each a set of hostile bodies (each known field as int, list, dict, null and a very long string; a non-object JSON), and assert status < 500 and that no job starts with a non-str argv element. Step 2 fixes what fails, route file by route file, in the existing hand-validator style (isinstance checks answering 400/422 with the field named, like _token_body and jobs_models.validate_*). No Pydantic models and no refusal of unknown body fields here: that is a breaking style change the finding does not require (E12e is parked). Action bodies on git workspaces are covered by E1's validators; store-workspace action bodies (ui/jobs_store.py, run in-process) are part of this sweep.

**Tests first.**

- tests/test_ui_body_checks.py (new, pure; one per validator added in step 2, for example test_workspace_name_must_be_a_str): each hand validator is a function tested without an app
- tests/test_ui_api_body_types.py (new): test_no_mutating_route_answers_500_on_wrong_typed_body (parametrized over app.routes; tmp_path manager with a file store, in-memory control plane and fake OIDC so admin and auth routes exist)
- tests/test_ui_api_body_types.py: test_non_object_body_is_422
- tests/test_fix_ui_security_payload.py stays green

**Files.** `packages/vmn-exp/src/vmn_exp/ui/server.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_comments.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_reports.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_settings.py`, `packages/vmn-exp/src/vmn_exp/ui/auth/oidc_routes.py`, `packages/vmn-exp/tests/test_ui_api_body_types.py (new)`

**Risk.** Which routes fail is unknown until the sweep runs; the file list is the likely set, not a verified one. server.py is 839 lines, so fixes there should move validation into the route module being touched rather than grow it. One worktree per route file.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/server.py:327-342 (add_workspace), 587 (run_action body: dict = None)`; `packages/vmn-exp/src/vmn_exp/ui/routes_comments.py:49-58 (reply_to, anchor unchecked)`; `packages/vmn-exp/src/vmn_exp/ui/routes_reports.py:85-92`; `packages/vmn-exp/src/vmn_exp/ui/auth/oidc_routes.py:62-65 with auth/device.py:58`; `packages/vmn-exp/src/vmn_exp/ui/routes_admin.py:26-34 (_token_body: the house style of a hand validator answering 422)`; `grep under ui/: 18 'body: dict', 0 'response_model|BaseModel|pydantic'`

<a id="e14a"></a>
### E14a. Web: the vitest suite as a blocking CI stage, then ESLint (also plan 43 F15)

P1 · M

This is the single item for web tests in CI. Plan 43's F15 points here and has no work of its own.

**Problem.** The web client has 530 test files under packages/vmn-exp/webui/src and a `test` script (`vitest run`), but nothing in CI runs them: ci/pipeline.py's stages are lint, tests_core, tests_exp, typecheck, stamp, build and upload, and its only npm call is `make _build_ui` inside tests_exp, which runs `tsc -b && vite build`. The behaviour that protects a solo user's first screen lives only in those tests, so a regression there ships unnoticed. The web client also has no linter: package.json has no eslint dependency and no lint script.

**Approach.**

Three steps, in this order.

1. One-off fix pass. Run `npm test` in packages/vmn-exp/webui once, record the duration and the failing tests, and fix them (product code first; a test that is itself wrong is a test edit not named here, so it stops and asks). The stage is not added until the suite is green.
2. Blocking stage. A Makefile target `_test_ui` (`npm test --prefix packages/vmn-exp/webui`) and a `tests_webui` stage in ci/pipeline.py that runs `make _build_ui` (install and `tsc -b`) and then `make _test_ui`. It is declared deterministic with `packages/vmn-exp/webui` as its input and `reports/tests_webui.xml` as its output: `_test_ui` passes vitest's JUnit reporter and that output file, because the caching test asserts that every cached test stage declares outputs (ci/test_pipeline.py:245). It is placed before tests_exp, added to the pipeline's stage list and to the stages the release stages wait for. It is blocking: no `check=False`.
3. ESLint. eslint with typescript-eslint and eslint-plugin-react-hooks as devDependencies, a flat eslint.config.js, a `lint` script, and a Makefile target `_lint_ui` that the same stage runs after the tests. `react-hooks/rules-of-hooks` and `react-hooks/exhaustive-deps` are errors; stylistic rules are off. Fix what they report in small commits with vitest green, then make the lint step part of the stage.

ci/README.md and CLAUDE.md's Running Tests name the stage and the two make targets (the CLAUDE.md test-lane lines are approved in plan 37). Pipeline-stage tests live in ci/test_pipeline.py.

**Tests first.**

- ci/test_pipeline.py::test_the_pipeline_runs_the_webui_unit_tests: the loaded pipeline module lists a tests_webui stage; calling it with a recording ctx runs `['make', '_build_ui']` then `['make', '_test_ui']`, both checked. Red today. A fake ctx, no npm.
- ci/test_pipeline.py::test_the_webui_stage_fails_on_a_test_failure (the recording ctx raises on `_test_ui`; the stage does not swallow it)
- ci/test_pipeline.py: `("tests_webui", {"packages/vmn-exp/webui"})` added to the parametrize list of test_test_stages_are_cached_on_the_sources_they_read (:232-237), and `tests_webui` added to the order asserted in test_release_stages_run_after_tests_in_order (:251-258). Both are approved additions. The first one fails until the stage declares its report output.
- ci/test_pipeline.py::test_the_webui_stage_runs_lint_after_the_tests (step 3; red until `_lint_ui` is wired)
- `npm run lint` is the red step for each rule fix.

ci/test_pipeline.py runs only in the muster venv (`pytest.importorskip("debug_router")`).

**Files.** `ci/pipeline.py`, `ci/test_pipeline.py`, `Makefile`, `ci/README.md`, `CLAUDE.md (Running Tests)`, `packages/vmn-exp/webui/package.json`, `packages/vmn-exp/webui/eslint.config.js (new)`

**Risk.** Not settled by reading: the exact vitest flags for the JUnit report (`--reporter=junit --outputFile=<path>` in vitest 2; confirm against the installed 2.1.x in step 1). The suite's duration and its failures today were not measured: step 1 is sized on the assumption that few tests fail. If many do, report the list before fixing. exhaustive-deps fixes can change render behaviour; where a fix is not obviously safe, disable the line with a reason rather than rewrite the effect. The stage needs npm on the CI host, which tests_exp already requires. New devDependencies only. Plan 44 G3 and plan 41 D15 also add stages to ci/pipeline.py; they are separate stages and do not conflict beyond the stage list line.

**Owner decision (2026-11-11).** Web tests and ESLint are a blocking CI stage after a one-off fix pass. E14a and plan 43 F15 are one item, kept here.

**Evidence.** `packages/vmn-exp/webui/package.json:6-11 (scripts: dev, build, preview, test; no lint), 22-32 (devDependencies; no eslint)`; `ci/pipeline.py:134-152 (tests_exp; the only npm call is 'make _build_ui' at :149), 155-159 (typecheck is report-only, check=False), 230-234 (stage list)`; `Makefile:12-15 (_build_ui: npm install, npm run build)`; `ci/test_pipeline.py:1-30 (muster venv only), 232-244, 251-258`; `packages/vmn-exp/webui/src (530 *.test.ts(x) files, 49 of them in src/__tests__; counted with find at 59becdd5)`; `packages/vmn-exp/webui/src/pages/Experiments/__tests__/JobsKind.test.tsx (the solo first-screen tests plan 43 F13 cites)`

<a id="e3"></a>
### E3. OIDC: verify the id_token signature against the IdP's JWKS

P2 · M · depends on E2 · second reviewer required

**Problem.** With TLS enforced (E2) skipping the signature is permitted by OIDC Core 3.1.3.7, but the token's alg is never read (alg=none passes) and there is no defence against a compromised TLS-terminating proxy between server and IdP. Security reviews will flag it.

**Approach.**

New ui/auth/jwks.py (under 150 lines), standard library only.

- `class JwksVerifier` with `__init__(self, http, clock)` and `verify(self, id_token, jwks_uri)`, raising OIDCError. `http` is the same interface the authenticator already uses (`get_json(url)`); `clock` returns seconds. Neither has a default: both are passed in by cli._oidc_chain, which is called from server_app (ui/cli.py:169-180, the `vmn-exp ui` app factory wiring) and builds one `UrllibHttp()` for both the authenticator and the verifier.
- RS256 only. Parse the JOSE header; any alg other than RS256 (including none, ES256, PS256) fails closed with a message naming the alg.
- Pick the key by kid from a cached JWKS. An unknown kid triggers one re-fetch, rate-limited by the clock (at most one fetch per 60 s); still unknown fails closed. No jwks_uri in the discovery document fails closed.
- Require a modulus of at least 2048 bits and a signature exactly the modulus length. Compute `pow(sig, e, n)` and compare byte-for-byte (hmac.compare_digest) with the EMSA-PKCS1-v1_5 encoding built from sha256 of the signing input. Encode then compare; the decrypted block is never parsed.
- OIDCAuthenticator receives the verifier as a constructor parameter and calls it at the top of checked_claims, which covers the browser flow (complete) and the device flow (DeviceFlow.poll). metadata() applies E2's require_https to jwks_uri.

The module docstring of oidc.py (lines 1-9, the rationale for skipping the signature) is rewritten. server.md documents RS256-only and what an operator sees with an ES256-only IdP.

Review: the pull request for jwks.py and its tests gets a second reviewer who reads the verification code line by line against RFC 8017 section 8.2.2 and RFC 7515 before merge. That is part of the item's definition of done.

**Tests first.**

- tests/oidc_test_keys.py (new helper, not a test): one fixed 2048-bit RSA test keypair as integer constants (generated once offline), `sign_rs256(header, claims)` built on `pow(m, d, n)`, and the matching JWKS dict. Pure Python.
- tests/test_ui_auth_jwks.py (new, pure; fake http, fake clock): test_valid_rs256_token_verifies, test_tampered_payload_is_refused, test_alg_none_is_refused, test_es256_fails_closed_naming_alg, test_wrong_key_is_refused, test_short_modulus_is_refused, test_signature_of_wrong_length_is_refused, test_unknown_kid_refetches_once_then_refuses, test_refetch_is_rate_limited_by_the_clock, test_missing_jwks_uri_fails_closed
- tests/test_ui_auth_oidc.py: test_complete_refuses_unsigned_id_token
- tests/test_ui_device_login.py: test_device_poll_refuses_unsigned_id_token

Existing fixtures changed (approved; assertions are not weakened):
- tests/test_ui_auth_oidc.py:24-26 `_jwt` builds a token with the literal signature `sig`. It signs with the test key instead, and FakeIdP.get_json (:46-52) adds `jwks_uri` to the discovery document and serves the JWKS at that URL. `_client` (:67-82) passes `JwksVerifier(idp, clock)` to OIDCAuthenticator.
- tests/test_ui_device_login.py:24-50 FakeDeviceIdP: the same two additions; it imports `_jwt` from test_ui_auth_oidc (:11), so the signing change reaches it. Its authenticator construction at :62 passes the verifier. The denying IdP fake at :119-123 is checked for the same need.

**Files.** `packages/vmn-exp/src/vmn_exp/ui/auth/jwks.py (new)`, `packages/vmn-exp/src/vmn_exp/ui/auth/oidc.py`, `packages/vmn-exp/src/vmn_exp/ui/cli.py`, `packages/vmn-exp/tests/test_ui_auth_jwks.py (new)`, `packages/vmn-exp/tests/oidc_test_keys.py (new)`, `packages/vmn-exp/tests/test_ui_auth_oidc.py`, `packages/vmn-exp/tests/test_ui_device_login.py`, `docs/vmn-exp/server.md`, `docs/vmn-exp/upgrading.md (row)`

**Risk.** Hand-written signature verification, even at 40 lines, is why the second reviewer is required. An IdP that signs ID tokens only with ES256 or PS256 stops working on upgrade; the login error names the alg, and the change needs an upgrading.md row (per plan 43 F9). An IdP whose discovery document has no jwks_uri also stops working. The JwksVerifier interface is the seam where another implementation could be wired later; none is planned. Not settled by reading: which algorithm the client's IdP signs with; check one real ID token header before release.

**Owner decision (2026-11-11).** Verify ID-token signatures: RS256 in the standard library behind a `JwksVerifier` interface with injected http, and a second reviewer on the crypto code. No new dependency.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/auth/oidc.py:1-9 (rationale), 51-56 (jwt_claims: base64 decode of the payload only; the header is never read), 131-143 (checked_claims: iss, aud, exp, nonce, sub only)`; `packages/vmn-exp/src/vmn_exp/ui/auth/oidc.py:70-76 (http and clock are constructor parameters, with real defaults)`; `packages/vmn-exp/src/vmn_exp/ui/auth/oidc.py:81-90 (metadata(): the discovery document is cached; jwks_uri is not read)`; `packages/vmn-exp/src/vmn_exp/ui/auth/device.py:69 (the device flow calls checked_claims)`; `packages/vmn-exp/src/vmn_exp/ui/auth/oidc_http.py:11-14 (get_json)`; `packages/vmn-exp/src/vmn_exp/ui/cli.py:148-166 (_oidc_chain builds OIDCAuthenticator(config, control_plane))`; `packages/vmn-exp/pyproject.toml:22-29 (extras: ui, orjson, s3, gcs, azure; no crypto dependency)`; `packages/vmn-exp/tests/test_ui_auth_oidc.py:17 (ISSUER is https), 24-26 (_jwt: unsigned), 29-64 (FakeIdP)`; `packages/vmn-exp/tests/test_ui_device_login.py:11,24-50,62`

<a id="e11"></a>
### E11. Optional paging for the reports, tokens and models lists

P3 · S

**Problem.** GET .../reports returns every report row, GET /tokens every token record and GET .../models every model row. All three are cheap reads (an in-memory report index; one control-plane query; the registry snapshot since 8951f280), but the responses are unbounded. Tokens grow without limit: every 'vmn-exp login' mints a new 90-day token, and the sweep deletes only expired sessions and login states, never tokens.

**Approach.**

Add offset and limit (through http_params.clamp_page) to the three routes. Without limit the response is as today. Reports add 'total' to the existing object. Models add 'total' beside 'models': ModelListing.response(kind, offset=0, limit=None) slices the name-ordered rows it already builds in memory (this is the paging the dropped E10 carried). Tokens stay a bare list in both cases and carry the total in an X-Total-Count header, so there is one response shape. The web pages keep the unpaged call.

**Tests first.**

- tests/test_ui_models_listing_page.py (new, pure: a ModelListing built from hand-made objects with a `row` attribute; no storage): test_response_offset_limit_and_total, test_response_without_limit_is_unchanged, test_total_counts_after_the_kind_filter
- tests/test_ui_reports_api.py: test_reports_limit_offset_and_total, test_reports_without_limit_unchanged
- tests/test_ui_token_api.py: test_tokens_limit_offset_with_total_header, test_tokens_without_limit_is_the_full_list
- tests/test_ui_models_list_snapshot.py: test_the_list_route_pages_with_offset_and_limit

**Files.** `packages/vmn-exp/src/vmn_exp/ui/routes_reports.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_admin.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_models.py`, `packages/vmn-exp/src/vmn_exp/ui/readers/models.py`, `docs/vmn-exp/reports.md`, `docs/vmn-exp/server.md`, `docs/vmn-exp/models.md`, the HTTP API doc's model registry table

**Risk.** Additive. Deleting long-expired login tokens in the hourly sweep is the real fix for token growth; it changes what the admin list shows and is reported here as a follow-up, not planned.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/routes_reports.py:69-72`; `packages/vmn-exp/src/vmn_exp/ui/routes_admin.py:41-43 (bare list), 62-68 (audit already pages with clamp_page and total)`; `packages/vmn-exp/src/vmn_exp/ui/routes_models.py:50-54 (list route answers listings.get(storage).response(kind))`; `packages/vmn-exp/src/vmn_exp/ui/readers/models.py:143-165 (ModelListing: in-memory rows, name-ordered)`; `packages/vmn-exp/src/vmn_exp/ui/http_params.py:10-13 (clamp_page)`; `packages/vmn-exp/src/vmn_exp/ui/control_plane.py:95-101 (page/count exist; sweep_expired covers sessions and login states)`; `packages/vmn-exp/src/vmn_exp/ui/auth/device.py:72-74 (a token per login)`

<a id="e12d"></a>
### E12d. list_experiments: group its 24 query parameters into validated modes

P3 · M

**Problem.** One handler takes 24 query parameters (job_agg_nested was added by fe3b0e12) that select among flat paging, grouping, tree top/children and job aggregation; legal combinations are enforced by scattered ifs (top_q needs top, collapse_all needs group and top, more below). Illegal mixes are easy to send and hard to document. routes_leaderboard.py is 350 lines, over the repo's file-size rule.

**Approach.**

No URL change. Move the parameters into small Depends classes in a new ui/leaderboard_params.py (page, group, tree, job aggregation) and one pure function resolve_mode(...) returning a tagged mode or raising a 400 that names the conflicting parameters. list_experiments dispatches on the mode. Only the cross-checks that exist today move into resolve_mode; no new refusals in this item, so the web client cannot break. Stricter refusals of silently ignored combinations are a separate, later change once the mode table is documented.

**Tests first.**

- tests/test_ui_leaderboard_params.py (new, pure, table-driven): test_each_documented_combination_resolves_to_its_mode, test_top_q_without_top_is_refused, test_collapse_all_needs_group_and_top
- tests/test_ui_leaderboard_params.py: test_job_agg_nested_belongs_to_the_job_aggregation_mode
- tests/test_ui_leaderboard_etag_stable.py (new): the ETag of a fixed request is the same before and after the refactor (captured as a constant first)
- tests/test_fix_ui_api_list.py and the unknown-parameter tests stay green unchanged

**Files.** `packages/vmn-exp/src/vmn_exp/ui/leaderboard_params.py (new)`, `packages/vmn-exp/src/vmn_exp/ui/routes_leaderboard.py`, `docs/vmn-exp/ui-api.md (ui.md before plan 43 F5; one table: mode to parameters)`

**Risk.** A pure refactor of a hot route: the encoded-body cache keys (bodies LRU at routes_leaderboard.py:98) are built from these parameters and must come out identical; a test asserting the same ETag before and after for a fixed request guards that.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/routes_leaderboard.py:100-136 (signature 101-129, first cross-checks 132-136), 199-206 (a second handler repeats the top_q check)`; `packages/vmn-exp/src/vmn_exp/ui/query_params.py:36-40 (unknown-parameter refusal walks sub-dependencies)`

<a id="e14b"></a>
### E14b. Web: split vendor code out of the 572 KB entry chunk, with a size budget

P3 · S · depends on E14a

**Problem.** The built entry chunk is 572,317 bytes. Routes other than the three landing pages are already lazy, so the weight is the shell, the eagerly imported Experiments page and all vendor code in one file that every upgrade invalidates as a whole (files are revalidated, not hash-cached).

**Approach.**

rollupOptions.output.manualChunks puts react, react-dom, react-router-dom and @tanstack/* into a 'vendor' chunk that stays byte-identical across app releases, so the server's revalidation answers 304 for it. A small node script run at the end of 'npm run build' fails when assets/index.js exceeds a budget set just under the new size, so growth is noticed.

**Tests first.**

- web/scripts/check-bundle.mjs with its own vitest unit test (web/src/__tests__/checkBundle.test.ts): over-budget size fails, under-budget passes (the size is passed in; no real build in the test)
- red step: the script fails on today's 572 KB entry before manualChunks is added

**Files.** `packages/vmn-exp/webui/vite.config.ts`, `packages/vmn-exp/webui/scripts/check-bundle.mjs (new)`, `packages/vmn-exp/webui/package.json`

**Risk.** static_files.py and index.html rely on stable chunk names; 'vendor.js' is stable too. vite.export.config.ts (the export bundle) is a separate build and must be checked not to inherit the split.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/static/assets/index.js (572317 bytes; git-ignored build output of Nov 10, measured locally)`; `packages/vmn-exp/webui/src/routes.tsx:8-10 (AppsPage, WorkspacesHome, ExperimentsPage eager), 15-22 (lazy pages)`; `packages/vmn-exp/webui/vite.config.ts:14-27 (stable names, no manualChunks)`; `packages/vmn-exp/src/vmn_exp/ui/static_files.py:1-27 (no-cache plus conditional requests)`

<a id="e14c"></a>
### E14c. Web: split pages/StampTree.tsx (749 lines)

P3 · M · depends on E14a

**Problem.** pages/StampTree.tsx is 749 lines, well over the repo's 200-300 line rule, mixing layout computation, the graph view and the side panel.

**Approach.**

Extract the layout computation into a pure module first, behind a unit test that pins the positions the current code computes for a small DAG fixture; then move the graph view and the side panel into their own files, each under 300 lines. No behaviour change; existing tests untouched.

**Tests first.**

- web/src/__tests__/stampTreeLayout.test.ts (new): layout of a small DAG fixture equals the positions captured from the current component

**Files.** `packages/vmn-exp/webui/src/pages/StampTree.tsx`, `packages/vmn-exp/webui/src/pages/StampTree/ (new files)`

**Risk.** Refactor of a low-traffic page; do it only with the layout test in place and E14a's lint running.

**Evidence.** `packages/vmn-exp/webui/src/pages/StampTree.tsx (749 lines)`; `packages/vmn-exp/webui/src/routes.tsx:17 (lazy page, git workspaces only)`

<a id="e7"></a>
### E7. Job polls across replicas: document sticky routing, a 404 poll reads as unknown

P3 · S · depends on E6

**Problem.** The job table is a per-process OrderedDict. With several replicas behind a load balancer (server.md documents replicas sharing the Postgres cache and says nothing about jobs), the poll after POST .../actions can land on another replica and answer 404 'Job not found'. The web client's useJob hook stops polling on any error and shows the error text, so the UI reports a failed action that is in fact running or done. The same happens after a server restart.

**Approach.**

Two parts, no server change.

1. server.md, under "Postgres and replicas": a job lives in the memory of the replica that started it. A multi-replica deployment needs sticky routing (session affinity) for POST .../actions/{action} and GET /api/v1/jobs/{id}, or one replica that takes mutations. Without it a poll can answer 404 for a job that is running.
2. Web: a pure function `pollOutcome(error)` in a new web/src/jobPoll.ts returns `"unknown"` for an HttpError with status 404 and `"error"` otherwise. useJob (web/src/components/ui.tsx:75-116) stops polling in both cases; for "unknown" it sets the job's status to `unknown` instead of setting the error. JobCard renders that as "job status unknown: this server no longer has the job. Reload to see the result." with the last log it had. `onDone` is not called for an unknown job, so no caller treats it as finished.

**Tests first.**

- web/src/__tests__/jobPoll.test.ts (new, pure): a 404 HttpError yields "unknown"; a 500 and a network error yield "error"
- web/src/components/__tests__/useJobUnknown.test.tsx (new; api.job mocked to reject with status 404): the card reads "status unknown", no error text is shown, polling stops, onDone is not called
- web/src/components/__tests__/fix_components.test.tsx stays green unchanged

**Files.** `docs/vmn-exp/server.md`, `packages/vmn-exp/webui/src/jobPoll.ts (new)`, `packages/vmn-exp/webui/src/components/ui.tsx`, `packages/vmn-exp/webui/src/types.ts (the Job.status comment)`

**Risk.** After E6 a job in another workspace or org also answers 404, on purpose; the client cannot tell that from a forgotten job, and "unknown" is the honest reading for both. The one-mutation-per-workspace rule stays per replica; cross-replica serialization of mutations is a non-goal. Callers of useJob that refresh on onDone (useArchiveJob.ts, Actions.tsx, NoteEditor.tsx and others) do not refresh for an unknown job; the message tells the user to reload.

**Owner decision (2026-11-11).** Document sticky routing and make the web client treat a 404 poll as unknown. Persisting jobs in the control plane is parked (E7b).

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/jobs.py:201-219 (in-memory table)`; `packages/vmn-exp/src/vmn_exp/ui/server.py:169 (JobRunner() per app), 666-671 (get_job: 404 'Job not found')`; `packages/vmn-exp/webui/src/components/ui.tsx:75-116 (useJob: polls every 500 ms; the catch at :102-105 stops and sets the error for any failure), 118-134 (JobCard)`; `packages/vmn-exp/webui/src/http.ts:13-14,73-74 (HttpError carries status)`; `packages/vmn-exp/webui/src/api.ts:194 (api.job)`; `packages/vmn-exp/webui/src/types.ts:97-103 (Job)`; `docs/vmn-exp/server.md:197-240 (replicas; nothing about jobs)`

<a id="e7b"></a>
### E7b. Persist jobs in the control plane

Parked · M · depends on E7, E6 · do not start

**Problem.** After E7 a poll that reaches a replica that did not start the job reads as unknown, not as the job's real status. Only a shared job table would give every replica the answer.

**Approach.**

Parked: the design is kept on record and is not to be built now. JobRunner takes an optional job_store (put(job_dict, expires_at), get(job_id)); production wires a control-plane-backed one, tests a dict fake; the runner writes on start and finish (status, exit_code, a log tail capped well under MAX_JOB_LOG_BYTES, workspace, org) and get() falls back to the store. A new control-plane kind 'job' with expiry (a migration for SQLite and Postgres, listed in RLS_TABLES), swept hourly.

**Tests first.**

- If reopened: tests/test_ui_jobs_shared.py: test_job_started_on_one_runner_is_readable_from_another (two JobRunners, one dict store), test_finished_job_log_is_stored_capped, test_no_store_means_local_only, test_stored_job_keeps_workspace_and_org.

**Files.** None while parked.

**Risk.** If reopened: persisted job logs can hold paths and tool output and would rest in the control-plane DB; cap and expiry bound it.

**Owner decision (2026-11-11).** Not now. E7 covers the supported deployment (sticky routing). Reopen only if replicas without sticky routing become a real deployment.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/control_plane.py:72-112 (fixed kinds, each its own table; put/get/pop/delete/list/page/count/scan)`; `packages/vmn-exp/src/vmn_exp/ui/migrations/ (0001-0006)`; `packages/vmn-exp/src/vmn_exp/ui/tenancy.py:20-24 (RLS tables)`

<a id="e5b"></a>
### E5b. Roles: periodic re-check with the IdP (refresh token)

Parked · L · depends on E5a, E3 · do not start

**Problem.** After E5a, removal from an IdP group is still not seen until the session or login token expires (up to the configured TTL; 90 days by default for a CLI login).

**Approach.**

Parked: the design is kept on record and is not to be built now. New ui/auth/recheck.py: when auth.oidc.recheck_minutes is set, login requests offline_access, the refresh token is kept in the control plane beside the session or login token, and on authenticate a credential whose last check is older than the interval is refreshed (refresh_token grant through the injected http and clock). New groups replace the stored ones; invalid_grant revokes the credential. An unreachable IdP keeps the last groups for one more interval and logs a warning.

**Tests first.**

- If reopened: tests/test_ui_auth_recheck.py: test_groups_updated_after_interval, test_invalid_grant_revokes_session_and_token, test_no_refresh_before_interval, test_idp_outage_keeps_groups_and_warns (fake http, fake clock, in-memory control plane).

**Files.** None while parked.

**Risk.** If reopened: stores IdP refresh tokens server-side (a new secret at rest). Adds an IdP call on the request path once per interval per credential; it must run off the event loop like the existing authenticate.

**Owner decision (2026-11-11).** No IdP re-check for now. After E5a, removal from an IdP group is seen at the next login, bounded by auth.oidc.session_ttl_hours and auth.oidc.login_token_ttl_days; set login_token_ttl_days low (for example 7) and use revoke-by-owner for urgent removals. Reopen only if near-immediate deprovisioning is required.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/auth/device.py:16 (LOGIN_TOKEN_TTL_SEC = 90 days)`; `packages/vmn-exp/src/vmn_exp/ui/auth/oidc.py:37 (scopes: no offline_access)`

<a id="e12c2"></a>
### E12c2. Narrow the ValueError handler to named client errors

Parked · M · depends on E12c, E12a · do not start

**Problem.** After E12c the swallowed ValueErrors are visible in the log but still answer 400, so a server bug is still reported to the caller as their mistake.

**Approach.**

Parked: the design is kept on record and is not to be built now. Introduce InvalidName(ValueError) in the SDK next to the path-component validators, raise it at the sites the log names (still a ValueError, so SDK callers are unaffected), and register the 400 handler for InvalidName only. Other ValueErrors fall through to a logged 500.

**Tests first.**

- If reopened: tests/test_ui_api_errors.py: test_storage_invalid_name_is_400, test_unrelated_value_error_is_500_and_logged; sdk tests/test_storage_invalid_name.py: test_invalid_component_raises_invalid_name_subclass_of_value_error.

**Files.** None while parked.

**Risk.** If reopened: any input that gets a 400 by accident today becomes a 500 until its route validates it. Raise sites were not enumerated in this review.

**Owner decision (2026-11-11).** Not yet: log first. E12c ships and the handler keeps answering 400 for every ValueError. Reopen with the E12c log from real use and the E12a sweep as the list of raise sites that legitimately reach the handler; narrowing blind risks turning working 400s into 500s.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/server.py:262-265`; `packages/vmn-exp-sdk/src/vmn_exp/storage/files.py:44,51 (record and app name refusals), 97-103 (artifact_name_for)`

<a id="e12e"></a>
### E12e. Typed request and response models, and a generated types.ts

Parked · XL · depends on E12a, E12b · do not start

**Problem.** No route declares a request or response model, so /api/openapi.json describes no payloads and web/src/types.ts (675 lines) is a hand-kept mirror that can drift from the server silently.

**Approach.**

Parked: the design is kept on record and is not to be built now. Pydantic request models for the 18 body handlers (replacing E12a's hand checks, and deciding then whether unknown fields are refused), response models for the small stable payloads first (meta, workspaces, apps, job, tokens, models list, reports list), web/src/types.gen.ts generated from /api/openapi.json in the web build, and the matching hand-written interfaces removed. Leaderboard and run-detail payloads (large, hot, rendered through SafeJSONResponse) stay hand-typed until measured.

**Tests first.**

- If reopened: tests/test_ui_openapi_contract.py: test_listed_routes_declare_response_models, test_generated_types_are_current.

**Files.** None while parked.

**Risk.** If reopened: response validation costs CPU on hot routes and can turn a harmless extra key into a 500; keep models to small payloads and measure with the existing perf tests before widening.

**Owner decision (2026-11-11).** Not yet: typed models wait. E12a to E12d ship in the existing hand-validator style. Reopen when vmn-exp is split into its own product or a second API client appears.

**Evidence.** `packages/vmn-exp/webui/src/types.ts (675 lines)`; `packages/vmn-exp/src/vmn_exp/ui/server.py:161 (openapi_url served; 0 response_model under ui/)`

## Dropped

- **E10 (serve GET /workspaces/{ws}/models from the registry snapshot):** done upstream by 8951f280 (the Models page lists from a background-refreshed registry snapshot: `ModelListing` in ui/readers/models.py:143-165, served by routes_models.py:50-54), c796563f (a write through the server re-reads only its model: `RegistrySnapshots.refresh_model`, registry_snapshot.py:165-174, called by the four mutating routes) and 2d3374a4 (the lineage and list snapshots share one `RegistryListings` listing per background refresh, server.py:791-792,808-809). Tests are in tests/test_ui_models_list_snapshot.py and tests/test_ui_registry_shared_listing.py. What is left: optional paging moved to E11; ui/registry_snapshot.py still reads time.monotonic() directly (:181, 193, 200, 228, 231), which is plan 44's to migrate; GET .../models/{name} still reads one model per request and stays a follow-up with no item.

## Review findings corrected or dropped

- **Finding 1 (premise): the older actions are safe because argparse rejects '-'-leading values** Only partly true, so the finding understates the problem. argparse accepts a negative-number token as an option value (packages/vmn-exp/tests/test_exp_rewind_cli.py:112 passes '--step -1' through to the handler) and treats any token containing a space as a value. packages/vmn-exp/src/vmn_exp/ui/jobs.py:116-117 renders keep with str(), so keep=-1 reaches prune.py:78 and deletes metas[:1]. Planned in E1 as a live bug.
- **Finding 1 (in-flight part): _metric_args accepts names starting with '-'** Already fixed in the main checkout: packages/vmn-exp/src/vmn_exp/ui/jobs.py:62-69 refuses a key that starts with '-' (commit 859da19b, with tests/test_ui_jobs_metric_names.py). Not re-planned; E1 builds on it.
- **Finding 8: error shape {error} is an inconsistency** The only server {error} body is POST /auth/device/token (packages/vmn-exp/src/vmn_exp/ui/auth/oidc_routes.py:62-67), which relays OAuth device-flow codes (authorization_pending, slow_down, invalid_grant; RFC 8628) from auth/device.py:17-26 for the CLI to poll on. Kept as is; E12b unifies the other four shapes.
- **Finding 10: unhashed bundle filenames are a tooling defect** By design and documented: packages/vmn-exp/webui/vite.config.ts:17-26 names chunks by name so index.html and routes stay stable, and packages/vmn-exp/src/vmn_exp/ui/static_files.py:1-27 serves everything with Cache-Control: no-cache plus conditional requests. Only the entry chunk's size is planned (E14b).
- **Finding 10: there are no end-to-end browser tests** Partly wrong. packages/vmn-exp/tests/test_uiload_browser.py and tests/uiload/browser.py use Playwright (confirmed by grep only; I did not read what they cover, the draft says reads, not mutations). There is no JS-side e2e runner, and none is planned; the gap that matters is that vitest and a linter are not in CI (E14a).
- **Finding 7: GET /workspaces/{ws}/apps is an uncached store listing** It is cached: packages/vmn-exp/src/vmn_exp/ui/server.py:357-369 answers through app_lists = TTLCache(APPS_TTL_SEC = 5) (server.py:96, 214), and a remote store's run counts come from the persisted index (362-366). The response is bounded by the number of apps. No change planned.
- **Finding 7: reports list is an N+1 against the store** Unpaginated is true (E11), but it is not a store walk: packages/vmn-exp/src/vmn_exp/ui/routes_reports.py:70-72 reads report_index(ws).reports(), an in-memory index kept by ReportIndexes (server.py:210-213, 757-759).
- **Finding 7: comment threads need pagination** GET .../comments takes a required target and returns that one thread (packages/vmn-exp/src/vmn_exp/ui/routes_comments.py:44-46); its size is bounded by one run's or report's discussion. It is one store read per request, a possible follow-up, but not a list endpoint.
- **Finding 6: /metrics is unauthenticated because it is outside /api** Half wrong. With any auth configured, /metrics carries require(VIEWER) (routes_cache.py:35) and RoleCheck.enforce answers 401 for a missing principal (auth/authz.py:63-65) even though the middleware's own 401 is /api-only (server.py:238). The real gap is the Host/Origin guard on a token-less server (E8).
- **Finding 2: skipping the signature is simply a bug** It is a documented choice (packages/vmn-exp/src/vmn_exp/ui/auth/oidc.py:1-9) that OIDC Core 3.1.3.7 permits for a token received directly from the token endpoint over TLS. What is missing is the TLS precondition (E2, P1); the signature check is defence in depth (E3, P2).

## Non-goals

- Re-planning the two review fixes, both landed (_metric_args '-' names, 859da19b; buffered.py _close after a failed ship, 59becdd5). E1 adds the structural choke point.
- Changing any URL under /api/v1 or splitting list_experiments into several endpoints; E12d keeps the route and its parameters and adds no new refusals.
- Replacing the static token or changing its all-workspace admin role; E4 only makes it optional alongside OIDC and documents it.
- Authorization finer than the existing viewer/editor/admin per workspace.
- SAML, mTLS, or any identity protocol other than the existing OIDC code and device flows.
- Cross-replica serialization of mutations, and persisting jobs (E7b is parked); E7 concerns only how a poll that reaches another replica is shown.
- Symlink containment inside the SDK (artifact_local_path, push uploads, report export run by the CLI user); E9 and E9b guard the server's serving paths only.
- Host-checking the static bundle and SPA shell (would break probes of token-less read-only servers).
- Serving GET .../models/{name} from the registry snapshot; deleting long-expired login tokens in the sweep. Both are reported as follow-ups (the Dropped note on E10, E11's risk note).
- Caching or paging comment threads, and paging /apps (bounded, already TTL-cached).
- Pydantic request models and refusing unknown body fields (E12e is parked).
- A JavaScript end-to-end framework; content-hashed asset names; rewriting the web's client-side CLI hints to the attached option form.
- Any change to core vmn (packages/vmn) beyond calling its parse_user_commands in the E1 fuzz test. E1 emits core's existing long options (--release-mode, --pr, --version) and changes no core parser.
- An IdP re-check of roles (E5b is parked), narrowing the ValueError handler (E12c2 is parked).

## What the critic changed in the draft

- Evidence refresh: the _metric_args fix is already in the checkout (jobs.py:62-69, commit 859da19b), so every jobs.py line reference in the draft was off by 6; corrected, and E1 no longer says 'rebase on the in-flight fix'.
- E1 problem statement corrected: argparse does accept some '-'-leading values (negative numbers, tokens with a space). Found a live bug the draft missed: prune keep=-1 deletes the oldest run (jobs.py:116-117, prune.py:78; admin-only). Raised the fuzz payload set accordingly ('-1', '-1 x', True).
- E1 simplified: two functions (opt, positional) instead of three part classes and a renderer; the fuzz test over an ACTIONS tuple is the enforcement. Noted that every option used has a long form. Dropped bulk_actions.py from the file list (it reuses the builders). Named the existing tests that pin argv (test_ui_jobs.py:147-232, 293-308; test_fix_ui_jobs_tags.py; test_ui_jobs_push.py; test_ui_jobs_rewind.py; test_ui_jobs_metric_names.py:43).
- E9 kept at P0 but the helper now passes through backends with no local record dir (the S3 cache path) and leaves cli/report_export.py alone (it runs as the CLI user). Added E9b: other server reads (read_file_from at local.py:277-279, the output tail in failure_context.py, the artifact listing walk) also follow symlinks; the draft's two-route fix would have left the output-tail leak open.
- E6: added org scoping. Workspace names are per org under multi tenancy (tenancy.py:20-24), so the draft's workspace-only check would still leak across orgs.
- E2 demoted P0 to P1 (it guards a misconfiguration; nothing is exploitable on a correctly configured https IdP) and extended: UrllibHttp follows redirects, including https to http, so the opener must refuse them. Corrected the fakes' names (FakeIdP, FakeDeviceIdP; there is no FakeHttp/FakeClock in those files) and flagged that existing fixtures may use http issuers.
- E3 demoted P1 to P2 (spec-permitted once E2 holds) and hardened: minimum modulus size and signature-length checks with tests; noted the fixture impact on FakeIdP-based tests.
- E4: the warning at cli.py:294-298 has the same token-only test; included in bind_refusal. Added the doc note that an OIDC-only server needs an admin role mapping on '*'. Named the two pinned tests in test_ui_cli.py.
- E5a: revoke-by-owner now also closes that principal's browser sessions (the draft left a deprovisioned user's 12 h session alive). Removed the now-unused OIDCConfig.role_mappings. Named the two tests that pin frozen roles (test_ui_device_login.py:97-106, test_ui_auth_oidc.py:88-110).
- E10: the draft's stale() design does not give read-your-writes in background mode, because get() returns the old snapshot and refreshes on a thread (registry_snapshot.py:132-146). Replaced with a synchronous one-model reread after each mutating route. Added a pure rows() unit test, a clock parameter (the file calls time.monotonic directly and is being touched), and moved tests off the app_layout git fixture onto tmp_path file stores.
- E8 narrowed from every path to /api, /metrics and /auth: a Host check on '/' would 403 health probes of token-less read-only servers. First test is now a pure RequestGuard test.
- E12a rewritten: no Pydantic and no extra='forbid' across 18 handlers (a breaking style change beyond the finding); it is a hostile-body sweep plus fixes in the existing hand-validator style. Size L to M. Pydantic moved under E12e.
- E12c split: logging the swallowed ValueError with its stack is a safe S change now (E12c); narrowing the handler (E12c2) waits for that evidence. The draft's blind narrowing admitted it had not enumerated raise sites. Dependency order changed so E12b builds on the handler's new home in api_errors.
- E12d: removed 'stricter refusals of combinations that were silently ignored' from this item (it could break the web client); added an ETag-equality guard because the body cache keys derive from these parameters.
- E11: tokens paging keeps one response shape (bare list plus X-Total-Count) instead of the draft's two shapes. Noted the real growth cause: a token per login, never swept (control_plane.py sweep covers sessions and login states only).
- E7 demoted P2 to P3 and the recommendation flipped: document sticky routing and soften the client's 404 first; persisting jobs (new table, migration, logs at rest) is a separate, later choice. Added org to the stored fields and RLS_TABLES if persisted.
- E14a: confirmed ci/test_pipeline.py exists, so the stage gets a real unit test; ordered CI-runs-vitest before adding ESLint. E14b split into E14b (vendor chunk and budget, S) and E14c (StampTree split, M): unrelated diffs.
- E13: the route-coverage test must also build an app with OIDC and a control plane, or /auth/* and admin routes never appear; /metrics and /auth need a documented home too.
- Refuted list: added two entries about finding 1 (the argparse premise; the already-landed metric fix). Marked the Playwright claim as grep-confirmed only.
