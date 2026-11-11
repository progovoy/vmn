# Plan 39: vmn-exp review fixes, CLI identity, output and surface

> Workstream B of the 2026-11-11 vmn-exp product review. The index, the
> milestone order and the cross-stream conflicts are in
> [37-vmn-exp-review-fixes.md](37-vmn-exp-review-fixes.md). Each item was drafted by a
> planner that read the code, then revised by a critic that re-checked the
> evidence and looked for tests pinning today's behaviour.
>
> Sizes: S under a day, M 1-3 days, L about a week, XL more. Priorities: P0 security or data loss, P1 blocks adoption or misleads users, P2 quality, P3 nice to have.

Status: **proposed** (2026-11-11). Owner decisions of 2026-11-11 are applied in this file.

Solo impact: see each item's risk line; nothing here may make the single-user case worse.

## Summary

Fifteen items. Two more are dropped: B5c (absorbed into plan 42 E1) and B9c (measured, not worth doing). The draft was checked against the main checkout and revised; timings were taken in a scratch clone outside the repo, with its remote pointed at a scratch bare repo.

**State of the code (re-checked at 59becdd5).** The plan was drafted at 25f03f3d; master has gained 28 commits since (26 from upstream and the two review fixes, 859da19b and 59becdd5). Of the source and test files this plan cites, only `ui/jobs.py` (the landed `_metric_args` fix, 859da19b) and `cli/skill.py` (baseline `pool_by` text) changed, and no cited line moved in the vmn-exp files. Two core citations were corrected (`cli/args.py:55-58, 94-98`, `cli/entry.py:293`). Nothing planned here was done upstream: the Models snapshot, absolute `artifact_path` downloads, baseline `pool_by`, nested job aggregates, the web default-view changes and the thread-pool fix touch none of these items.

**What the owner decided (2026-11-11)**
- **B1.** `vmn-exp --version` prints vmn-exp's own version only, with no core version beside it.
- **B3.** Listings not in storage order are flat, each child marked `^[N]`.
- **B4c.** A run with only untracked files opens on its own file list.
- **B5b and B5d ship together.** A flag an action does not own exits 2, and `vmn-exp <action> --help` lists only that action's flags. No argparse subparsers.
- **B5c is dropped here.** Plan 42 E1 was decided as the uniform `--flag=value` argv form through one builder, which covers everything B5c planned.
- **B6, B7.** `--json` on `compare` and `comments` only; exit codes stay 0/1/2 plus the child's code, documented.
- **B9d.** Re-measure after plan 38 A5 and A12 (adoption, which now also covers rerun and sweep trials), then trim redundant git calls. Reusing the supervisor's code identity is not done.
- **Releases.** Everything ships in 0.1.x patch releases. Each behaviour change gets an `upgrading.md` row and a changelog entry (plan 43 F9, F10).
- **Test edits.** The test edits named in this file are approved. An edit this file does not name still stops and asks, per the repo rule.

**What the draft got wrong**
- **B5b (subparsers) would break existing tests it did not name.** Seventeen exp test files call `parse_user_commands` directly, so argv normalization in `main._to_vmn_argv` never runs for them. Affected: `test_experiment.py:471-476` (`["experiment", "--latest", "my_app"]`), `test_docs_similar_statements.py:80-86` (`similar --help` must contain `--note NOTE`) and `test_exp_backend_removed.py:80-85` (`exp --help` must contain `--bucket`). B5b enforces flag ownership after parsing on the unchanged flat parser. Per-action help is B5d.
- **B8's claim that a normalizer keeps `args.ui_args` is false as written.** `test_ui_cache_cli.py:43` and `test_ui_backup_cli.py:24` read `ui_args` straight from `parse_user_commands`. B8 now has the subparsers write `ui_args` themselves.
- **B5c changed an argv shape that tests pin** (`test_ui_jobs.py:146-156`, `178-195`, `308`). The owner chose that uniform shape and approved rewriting those tests; the work is plan 42 E1.
- **B9a's required constructor parameters would break `test_exp_rerun_recording.py:140,155,165`**, which build `_Supervision` positionally. The loop is extracted into a new injected module instead; the constructor is untouched.
- **B7 planned to change `ui backup` and `ui diag` usage errors that already return 2** (`backup_cli.py:70`, `diag_cli.py:37`). Removed, along with the constants module.

**Run overhead, now measured (finding 7)**

| Case (this machine, local store) | Wall |
|---|---|
| `vmn-exp run app -- true` | 0.47 s |
| `vmn-exp run app -- python -c pass` | 1.02 s |
| `vmn-exp run app -- sleep 0.3` | 1.00 s |
| 5-metric SDK script alone | 0.43 s |
| same script under `vmn-exp run` | 1.0 s |

- The reported 5 s for a 1.5 s job did not reproduce in absolute terms; the roughly 2.3x ratio did.
- The fixed 0.5 s poll sleep is the largest removable cost (up to 0.5 s per run and per sweep trial). B9b is P1.
- SDK `start_run` spends 0.30 of its 0.32 s in `gitmode.checkout_source`, rebuilding a stamper with about 15 git subprocesses. Under `vmn-exp run` this repeats work the supervisor did moments earlier. Plan 38 A5 and A12 remove that repeat for the script a run, rerun or sweep trial launches; B9d re-measures what is left.
- The env-probe subprocess costs at most 0.05 s, so B9c is dropped.
- The no-op wrap splits as about 0.2 s process start and imports, 0.09 s stamper init, 0.17 s create and finish.

**Git processes, counted (B9a, at 286c7b4e, in-process on a bootstrapped app; `packages/vmn-exp/tests/test_exp_run_git_budget.py`).** `vmn-exp run app -- true`: 16. SDK `start_run`: 16. A second `start_run` in the same process: 16. Bounds are these plus 2. The `start_run` calls by subcommand: 3 remote, 3 diff, 2 rev-parse, 2 cat-file, 2 tag, 1 each of ls-files, rev-list, format-patch, config (`git config user.email`, a plain `subprocess.run`, also counted because the patched `git_cmd.subprocess` is the `subprocess` module itself). `remote get-url --all origin` three times and `tag --points-at HEAD` twice are the first candidates for B9d.

**New bug found while measuring:** `vmn-exp --debug run app -- true` fails with `usage: vmn ... invalid choice: 'run'`, because `_to_vmn_argv` passes any argv starting with `-` through unchanged. Folded into B1.

**Order.** B9a, B9b, B1, B2, B4a, B4b, B4c, B6, B3, B5a, B5b with B5d (one release), B8, B7, B9d. Constraints from other plans:
- Plan 38 A4 (`--no-adopt`, and the `supervised_env` extraction from `_Supervision._start`) lands before B9b, B1 and B5a. Plan 44 G8 comes after B9b and injects io into B9b's `watch()`; it does not extract a second tick.
- B6 and plan 42 E1 land before B5a, so the action-to-flag table is audited once with `--json` on `compare`, `--no-adopt` and E1's long-form flags in it.
- B9a lands before plan 38 A5; B9d starts only after A5 and A12 have shipped.
- B2, B3, B6, B5a and B5b land before plan 44 G15, which moves what is left of `cli/experiment.py` and keeps this plan's module names (`cli/compare_view.py`, `cli/list_layout.py`).
- Once plan 44 G1 (the IO ratchet) is in, an item that adds or removes a direct IO call updates `io_boundary_known.py` in the same commit (B1's version reader, B9b's loop).

## Items

| Id | Pri | Size | Item | Owner decision |
|---|---|---|---|---|
| [B1](#b1) | P1 | M | vmn-exp gets its own prog name, version and command list; root flags no longer break bare actions | decided |
| [B2](#b2) | P1 | S | `show` and `compare` print params as params, not under Metrics |  |
| [B3](#b3) | P2 | S | `list` rows are flat with a `^[N]` parent marker when the order is not storage order | decided |
| [B4a](#b4a) | P1 | S | Patch payload always names the untracked files a run captured |  |
| [B4b](#b4b) | P1 | S | Changes card lists untracked files next to the tracked diff |  |
| [B4c](#b4c) | P1 | S | A run with only untracked files offers its own patch as the default baseline | decided |
| [B5a](#b5a) | P2 | L | Move the experiment flags into per-group modules with an audited action-to-flag table (no behaviour change) |  |
| [B5b](#b5b) | P2 | M | Reject flags an experiment action does not own (exit 2), on the unchanged flat parser; ships with B5d | decided |
| [B5d](#b5d) | P2 | M | `vmn-exp <action> --help` lists only that action's flags; ships with B5b | decided |
| [B6](#b6) | P2 | S | `--json` on `compare` and `comments`; accurate `--json` help | decided |
| [B7](#b7) | P3 | S | Document the exit-code contract; the remaining handler-detected usage errors return 2 | decided |
| [B8](#b8) | P2 | M | `vmn-exp ui` maintenance verbs become real subcommands with their own flags |  |
| [B9a](#b9a) | P2 | S | Record where `vmn-exp run` spends its time and pin the git-process cost with budget tests |  |
| [B9b](#b9b) | P1 | S | Supervision loop wakes when the child exits instead of sleeping a fixed 0.5 s |  |
| [B9d](#b9d) | P2 | M | Re-measure the SDK repo capture after adoption (plan 38 A5, A12), then trim redundant git calls | decided |

<a id="b1"></a>
### B1. vmn-exp gets its own prog name, version and command list; root flags no longer break bare actions

P1 · M · after plan 38 A4 (same files)

**Problem.** For anyone running vmn-exp: `--help` prints `usage: vmn` and lists core commands (init, stamp, release, goto...), `--version` prints vmn's version, and `ui --help` prints `usage: vmn ui`. The core parser hard-codes prog `vmn`, vmn's version, and registers every VMN_ARGS builtin before the plugin specs; vmn-exp's main has no way to say who it is. Also reproduced in a scratch repo: `vmn-exp --debug run app -- true` fails with `usage: vmn ... invalid choice: 'run'`, because `_to_vmn_argv` passes any argv starting with `-` through unchanged, so a root flag disables the bare-action shortcut. `skill`, `migrate` and `login` are intercepted before the parser and appear in no help.

**Approach.**

Core: add a frozen dataclass `Frontend(prog="vmn", version=None, builtins=True, epilog=None)` to `version_stamp/cli/plugin_api.py`, exported from `version_stamp/api.py` (one more `_LAZY_REGISTRY` row). `parse_user_commands(command_line, frontend=None)` uses `frontend.prog`, `frontend.version or dev_build.display_version()`, the epilog, and skips the VMN_ARGS loop when `builtins` is False. `vmn_run(command_line=None, frontend=None)` passes it through (`measure_runtime_decorator` forwards kwargs). The default keeps `vmn` byte-for-byte unchanged. `normalize_config_gen` and `normalize_worktrees` already no-op for other commands (args.py:117-146).

vmn-exp: new `cli/version.py` with `display_version(read_version)`. It returns the string the reader gives and `unknown` when the reader gives None. The real reader is today's `ui/shell_meta._vmn_exp_version` (`importlib.metadata.version("vmn-exp")`, None when the package is not installed), moved to `cli/version.py` as `installed_version`; `shell_meta` imports it from there. `vmn-exp --version` prints that one string and nothing else, for example `0.1.37`. The core version is not printed; `vmn --version` and the server's `/meta` still report it.

The body of today's `vmn_exp_run` moves to `run_argv(argv, read_version)`, where `read_version` is a required parameter with no default. It calls `vmn_run(vmn_argv, frontend=Frontend(prog="vmn-exp", version=display_version(read_version), builtins=False, epilog=...))`. `vmn_exp_run(argv)` keeps its one-argument signature and becomes the wiring line `return run_argv(argv, installed_version)`: it is what `main` and 27 test files call (`exp_helpers._experiment` among them), so the real reader is chosen there and no test changes. The identity tests call `run_argv` with a fake reader. The epilog lists the bare actions plus `skill`, `migrate`, `login`.

`_to_vmn_argv` becomes root-flag aware: skip leading `--debug`, then apply today's rule to the next token, so `vmn-exp --debug run app` maps to `--debug exp run app`. `--help`, `--version` and `--completion*` still pass through. The stamping-command guard (main.py:39-45) applies the same skip.

Afterwards `vmn-exp --help` shows `usage: vmn-exp` and only experiment/exp, model, report, comment(s), settings, sweep, ui. `vmn-exp list --help` reads `usage: vmn-exp exp ...` until B5d replaces it with the action's own help.

**Tests first.**

- tests/test_cli_frontend.py (core, unit, no git): test_default_frontend_keeps_vmn_prog_version_and_builtins; test_frontend_prog_version_and_epilog_replace_vmns (parse ["--version"] and ["--help"] with capsys under pytest.raises(SystemExit)); test_frontend_without_builtins_does_not_know_stamp
- packages/vmn-exp/tests/test_vmn_exp_cli_identity.py (unit, in-process `run_argv` with a fake reader, no repo): test_help_says_vmn_exp_and_lists_no_stamping_commands; test_help_names_skill_migrate_and_login; test_version_prints_only_the_vmn_exp_version (output is exactly the fake reader's string and does not contain the core version); test_ui_help_usage_starts_with_vmn_exp_ui; test_stamp_still_points_at_vmn_with_exit_2
- packages/vmn-exp/tests/test_vmn_exp_cli_identity.py (pure, display_version): test_display_version_returns_the_readers_string; test_display_version_without_installed_metadata_says_unknown
- packages/vmn-exp/tests/test_vmn_exp_cli_identity.py (pure, _to_vmn_argv): test_debug_before_a_bare_action_still_routes_to_exp; test_debug_before_an_own_command_is_left_alone; test_help_and_version_pass_through; test_debug_stamp_still_hits_the_stamping_guard

**Files.** `packages/vmn/src/version_stamp/cli/plugin_api.py`, `packages/vmn/src/version_stamp/cli/args.py`, `packages/vmn/src/version_stamp/cli/entry.py`, `packages/vmn/src/version_stamp/api.py`, `packages/vmn-exp/src/vmn_exp/cli/main.py`, `packages/vmn-exp/src/vmn_exp/cli/version.py`, `packages/vmn-exp/src/vmn_exp/ui/shell_meta.py`, `tests/test_cli_frontend.py`, `packages/vmn-exp/tests/test_vmn_exp_cli_identity.py`, `docs/vmn-exp/experiments.md`, `docs/vmn-exp/upgrading.md` (row; the file is created by plan 43 F9)

**Risk.** Touches core vmn's parser only through an optional argument whose default reproduces today's behaviour; the core test pins that, and tests/test_cli_plugins.py must stay green. Plan 35 (core IO) is still only proposed and also works in `cli/entry.py`; whichever lands second rebases. `vmn-exp --version` output changes from vmn's version to vmn-exp's, so a script parsing it breaks: it needs an `upgrading.md` row and ships in a 0.1.x patch release. A bug report now needs `vmn --version` as a second command for the core version. The vmn-exp version comes from installed metadata and carries no `+dev` marker in a source checkout, unlike vmn's. No real reader sits in a default argument: `run_argv` requires it and `vmn_exp_run` passes the real one, as the repo's IO rule asks of an entry point. Plan 44 G7 later gives `vmn_exp_run` an `io` argument; the reader then comes from that `io` and the wiring line moves with it. If G7 lands first, B1 takes the reader from G7's `io` from the start. Exp tests that call `parse_user_commands` directly (17 files) pass no frontend and keep seeing builtins, which is unchanged behaviour. `--completion*` stays on the root parser and still describes vmn completion (non-goal). Error strings such as "Run vmn --debug for details" (entry.py:293) still say vmn (non-goal). Import rule kept: vmn-exp reaches core only via version_stamp.api. Plan 40 C6 adds a top-level `buffers` command later; it must join `OWN_COMMANDS` and the epilog.

**Owner decision (2026-11-11).** `vmn-exp --version` prints vmn-exp's own version only. No core version in brackets.

**Evidence.** `packages/vmn/src/version_stamp/cli/args.py:55-58 (ArgumentParser("vmn"), version=dev_build.display_version())`; `packages/vmn/src/version_stamp/cli/args.py:94-98 (all VMN_ARGS builtins added, then plugin specs)`; `packages/vmn-exp/src/vmn_exp/cli/main.py:13-21 (OWN_COMMANDS; _to_vmn_argv: argv[0].startswith('-') returns argv unchanged)`; `packages/vmn-exp/src/vmn_exp/cli/main.py:26-46 (skill/migrate/login intercepted; stamping-command guard; vmn_run)`; `packages/vmn/src/version_stamp/cli/entry.py:159-162 (vmn_run -> parse_user_commands(command_line))`; `packages/vmn/src/version_stamp/cli/plugins.py:25-36 (core vmn loads only the vmn.plugins entry point, so `exp` is reachable only through vmn-exp's register_all)`; `packages/vmn-exp/src/vmn_exp/ui/shell_meta.py:25-37 (the existing metadata.version("vmn-exp") reader, and server_versions which keeps reporting both versions to /meta)`; `packages/vmn-exp/pyproject.toml:7 (vmn-exp version 0.1.37)`; `packages/vmn-exp/tests/exp_helpers.py:89-90 (the test helper calls vmn_exp_run(args_list))`; `packages/vmn-exp/tests/test_installation.py:152-159 (runs `vmn-exp --help`, must still exit 0)`

<a id="b2"></a>
### B2. `show` and `compare` print params as params, not under Metrics

P1 · S

**Problem.** `vmn-exp show` prints `lr: 0.01` under `Metrics:`. Numeric params are folded into the `metrics` map on purpose (sorting and charting use it), and `show` prints that map unfiltered. Non-numeric params are not printed by `show` at all. `compare` builds its `metric` table from the same map. The UI already separates the two with `is_folded_param`; the CLI does not.

**Approach.**

Add a pure helper `split_params(metrics, params, logged)` to `cli/views.py` returning `(logged metrics, params)`, built on `is_folded_param`.

`experiment_show`: print a `Params:` block with every param verbatim (from `fold_values(fold, "params")`, strings included, formatted `name: value` so the existing `lr: 0.25` assertion holds), then `Metrics:` with logged metrics only. A name that is both a param and a logged metric appears in both.

`experiment_compare`: rows for folded params go in a second table headed `param`, after the `metric` table.

`show --json` is unchanged; it already carries `params`, `metrics` and `logged_params`. `list` rows keep `lr=0.25` (pinned by test_experiment_params_entry.py:99-106; see non-goals).

**Tests first.**

- packages/vmn-exp/tests/test_cli_show_params.py (unit, plain dicts): test_split_params_moves_a_folded_param_out_of_metrics; test_split_params_keeps_a_metric_logged_under_a_param_name; test_split_params_keeps_non_numeric_params
- packages/vmn-exp/tests/test_cli_show_params.py (LocalSnapshotStorage on tmp_path, vcs=None): test_show_prints_a_param_under_params_not_metrics; test_show_prints_a_string_param; test_show_omits_the_metrics_heading_when_only_params_exist; test_compare_lists_params_in_their_own_table

**Files.** `packages/vmn-exp/src/vmn_exp/cli/views.py`, `packages/vmn-exp/src/vmn_exp/cli/experiment.py`, `packages/vmn-exp/tests/test_cli_show_params.py`, `docs/vmn-exp/experiments.md`, `docs/vmn-exp/upgrading.md` (row)

**Risk.** Human-readable `show`/`compare` text changes; scripts scraping it should use `--json`, which does not change. test_metric_policy_cli_compare.py, test_compare_goal_conflict.py, test_metric_summary_sdk_cli.py and the compare cases in test_experiment.py and test_fix_cli_exp.py assert compare text and must be re-run. No test edit is named for this item, so if one of them pins a param inside the metric table, stop and ask before touching it. The text change needs an `upgrading.md` row (plan 43 F9).

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/core/fold.py:255-259 (numeric params copied into fold["metrics"] unless logged)`; `packages/vmn-exp-sdk/src/vmn_exp/core/fold.py:297, 326-336 (fold_values, logged_params, is_folded_param)`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:879-884 (show prints fold_metrics under "Metrics:"; no Params block anywhere in experiment_show 827-897)`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:1032-1035, 1044-1086 (compare table from fold_metrics)`; `packages/vmn-exp/tests/test_experiment_params_entry.py:109-116 (asserts only that `lr: 0.25` appears in show output, so a Params block keeps it green)`; `grep for "Metrics:" in packages/vmn-exp/tests and tests returned no assertion on the heading`

<a id="b3"></a>
### B3. `list` rows are flat with a `^[N]` parent marker when the order is not storage order

P2 · S

**Problem.** `vmn-exp list --sort loss` indents child rows by tree depth although they are no longer under their parents, so the indentation says nothing. The row formatter indents by `depth` whatever order the rows are in, and the default order is also re-sorted when the schema declares a primary metric.

**Approach.**

New pure module `cli/list_layout.py` (experiment.py is already 1,227 lines): `list_layout(rows)` returns `(indent, parent_label)` per row.
- Rows in ascending `idx` (storage order): today's behaviour, indent = depth, no label.
- Any other order: indent 0, and each row with a parent gets a suffix naming it, `^[N]` when the parent is among the listed rows (N is the parent's `idx`), else `^<parent verstr>`.

`_format_list_row` takes the indent and label instead of reading `node['depth']`. `--json` is unchanged (rows already carry `parent`, `depth`).

**Tests first.**

- packages/vmn-exp/tests/test_cli_list_layout.py (unit, plain dict rows): test_storage_order_keeps_depth_indentation; test_a_single_child_row_keeps_its_indent; test_sorted_rows_are_flat; test_a_sorted_child_names_its_listed_parent_by_idx; test_a_sorted_child_names_an_unlisted_parent_by_verstr; test_top_level_rows_get_no_marker; test_format_list_row_uses_the_given_indent_and_marker

**Files.** `packages/vmn-exp/src/vmn_exp/cli/list_layout.py`, `packages/vmn-exp/src/vmn_exp/cli/experiment.py`, `packages/vmn-exp/tests/test_cli_list_layout.py`, `docs/vmn-exp/experiments.md`, `docs/vmn-exp/upgrading.md` (row)

**Risk.** Text output of re-ordered listings changes (leading spaces removed, a suffix added). Listings in storage order are byte-identical, so the two existing indentation tests (test_experiment_nesting.py:279-299, test_fix_cli_exp.py:138-144) stay green untouched. An app whose schema declares a primary metric is re-ordered by default, so its default listing changes too; that is the reason for the `upgrading.md` row.

**Owner decision (2026-11-11).** Flat rows with a `^[N]` parent marker whenever the rows are not in storage order.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/experiment.py:692-710 (`'  ' * node['depth']` unconditionally, line 707)`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:668-680, 747-763 (rows sorted by sort_by_metric, then printed)`; `packages/vmn-exp-sdk/src/vmn_exp/core/log.py:174-185 (no --sort still sorts by the schema's primary metric)`; `packages/vmn-exp/tests/test_experiment_nesting.py:279-299 and packages/vmn-exp/tests/test_fix_cli_exp.py:138-144 (pin depth indentation in storage order, including a child listed alone with `--last 1`)`

<a id="b4a"></a>
### B4a. Patch payload always names the untracked files a run captured

P1 · S

**Problem.** For a run with both a tracked diff and untracked files, the `/patch` payload and `show --patch` mention only the tracked diff. `patch_payload` lists the untracked tarball's paths only when there is no text patch at all. In the reproduced case the script actually run (train2.py) was untracked and invisible, although restore brings it back.

**Approach.**

`views.patch_payload`: when text exists and any source has an untracked tarball, add `untracked_files` (the names from `_untracked_names`, capped at 200) and `untracked_total`. An unreadable tarball gives `untracked_files: []` with `untracked_unreadable: true`, so absence is never read as "none". With no tarball the payload stays exactly `{text, truncated}`.

`print_patch`: after the text, one stderr line: `untracked files captured, not printed: a, b, +N more (vmn-exp export or restore brings them back)`.

Plain `show` adds `untracked_files: captured` to its patch stats from `metadata["has_untracked_files"]` or tarball presence, without listing the tarball.

The route passes the new keys through unchanged; its ETag already covers the code identity.

**Tests first.**

- packages/vmn-exp/tests/test_exp_show_patch_views.py: test_a_text_patch_also_lists_the_untracked_files; test_a_deps_untracked_files_are_listed_beside_the_text_under_deps_prefix; test_an_unreadable_tarball_beside_text_is_flagged_not_dropped; test_untracked_names_are_capped_with_a_total; test_a_text_patch_without_a_tarball_has_no_untracked_keys
- packages/vmn-exp/tests/test_exp_show_patch_views.py: test_print_patch_notes_untracked_files_on_stderr (capsys)
- packages/vmn-exp/tests/test_cli_show_untracked.py (LocalSnapshotStorage, tmp_path): test_show_says_untracked_files_were_captured

**Files.** `packages/vmn-exp/src/vmn_exp/cli/views.py`, `packages/vmn-exp/src/vmn_exp/cli/experiment.py`, `packages/vmn-exp/tests/test_exp_show_patch_views.py`, `packages/vmn-exp/tests/test_cli_show_untracked.py`, `docs/vmn-exp/experiments.md`, `docs/vmn-exp/ui.md`

**Risk.** Additive JSON keys on `show --patch --json` and `/patch`; docs/vmn-exp/ui.md:1667-1668 and experiments.md:799-809 describe the payload and must be updated. Listing a large tarball decompresses it on each uncached `/patch` request (the route already loads it, and the ETag gives a 304 afterwards). The cap bounds payload size, not CPU; storing the names in metadata at capture time is a follow-up if that shows up.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/views.py:94-105, 112-133 (untracked names only in _no_text_payload; with text the payload is {text, truncated})`; `packages/vmn-exp/src/vmn_exp/cli/views.py:161-171 (print_patch prints text only)`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:865-869 (show's patch stats list working_tree/local_commits only)`; `packages/vmn-exp/src/vmn_exp/ui/routes_run_code.py:68-70 (route = patch_payload + patch_files(text))`; `packages/vmn-exp/tests/test_exp_show_patch_views.py:11-17, 103-105 (exact-dict equality for text payloads, with no tarball in the fixture, so they stay green if keys are added only when a tarball exists)`; `packages/vmn-exp/tests/test_exp_show_patch_views.py:36-43 and test_exp_show_patch_cli.py:171-191 (a corrupt tarball beside text; they assert only on `text`)`

<a id="b4b"></a>
### B4b. Changes card lists untracked files next to the tracked diff

P1 · S · depends on B4a

**Problem.** In the web UI the run page's Changes card shows only `FilesList` from the diff text. Untracked files are rendered only in the `untracked_only` branch, so a run that changed a tracked file and ran an untracked script shows just the tracked file.

**Approach.**

`RunChangesParts.tsx`: add `UntrackedList({files, total, unreadable})`, rendering each path with an `untracked` tag and one line saying they are not in the diff and that restore/export brings them back; `+N more` when `untracked_total` exceeds the list.

`PatchChanges` renders it after `FilesList` when `p.untracked_files` is present with text. `RunPatch` gains `untracked_total?` and `untracked_unreadable?`.

**Tests first.**

- packages/vmn-exp/webui/src/components/__tests__/RunChanges.test.tsx: "lists untracked files beside the tracked diff"; "says more untracked files exist than listed"; "says the untracked tarball could not be read"; "shows no untracked block for a tracked-only patch"

**Files.** `packages/vmn-exp/webui/src/components/RunChangesParts.tsx`, `packages/vmn-exp/webui/src/components/RunChangesBody.tsx`, `packages/vmn-exp/webui/src/apiRunCode.ts`, `packages/vmn-exp/webui/src/components/RunChanges.css`, `packages/vmn-exp/webui/src/components/__tests__/RunChanges.test.tsx`

**Risk.** Display only. RunChangesCss.test.ts checks the stylesheet and must stay green. The diff-against-another-run branch (`RunDiffChanges`) is untouched; whether that diff includes untracked files is a separate question (non-goal).

**Evidence.** `packages/vmn-exp/webui/src/components/RunChangesBody.tsx:35-47 (untracked_files used only when p.text == null)`; `packages/vmn-exp/webui/src/apiRunCode.ts:15-21 (RunPatch already types untracked_files)`; `packages/vmn-exp/webui/src/components/__tests__/RunChanges.test.tsx:55-151 (existing cases; none covers untracked beside text)`

<a id="b4c"></a>
### B4c. A run with only untracked files offers its own patch as the default baseline

P1 · S

**Problem.** Found while verifying finding 8. `/baselines` offers `base` (the run's own patch) only when it has a working-tree or local-commits patch. A run whose code is untracked files only, with no parent or previous run, gets no baseline, and the card prints "No code changes captured (clean tree) and no earlier run to compare with.", which is false. The `untracked_only` branch of `PatchChanges` cannot be reached in that case.

**Approach.**

Add a pure `has_own_code(presence)` to `ui/readers/patches.py`, true when any of working_tree, local_commits or untracked_files is present. `run_baselines` uses it instead of the inline `or`. The web then selects `base` and `PatchChanges` shows "Only untracked files were captured: ...". This holds whether or not the run has a previous run: `defaultBaseline` already prefers `base`, the same rule a run with a tracked patch follows, and it is not changed.

**Tests first.**

- packages/vmn-exp/tests/test_ui_patch_presence.py (new, unit, plain dicts): test_untracked_files_alone_count_as_own_code; test_a_tracked_patch_counts_as_own_code; test_no_patch_kinds_is_no_own_code
- packages/vmn-exp/tests/test_ui_run_baselines_api.py (second tier, existing fixture): test_base_exists_for_a_run_with_only_untracked_files; test_base_exists_for_an_untracked_only_run_that_has_a_previous_run

**Files.** `packages/vmn-exp/src/vmn_exp/ui/readers/patches.py`, `packages/vmn-exp/src/vmn_exp/ui/routes_run_code.py`, `packages/vmn-exp/tests/test_ui_patch_presence.py`, `packages/vmn-exp/tests/test_ui_run_baselines_api.py`, `docs/vmn-exp/ui.md`, `docs/vmn-exp/upgrading.md` (row)

**Risk.** Behaviour change beyond the empty case: an untracked-only run that also has a previous run now opens on `base` (the untracked file list) instead of the diff against the previous run. The previous-run diff stays one click away in the switcher. The `/baselines` payload has no ETag input for patch presence; test_the_etag_repeats (test_ui_run_baselines_api.py:102) must stay green. Upstream's baseline `pool_by` work (bf177869) is in `ui/baseline_views.py` and `ui/baseline_compare.py`, the job-page baseline, and does not touch `readers/baselines.py` or this route.

**Owner decision (2026-11-11).** Yes: an untracked-only run's own file list is its default baseline, also when it has a previous run.

**Evidence.** `packages/vmn-exp/src/vmn_exp/ui/routes_run_code.py:85-86 (has_patch = working_tree or local_commits)`; `packages/vmn-exp/src/vmn_exp/ui/readers/patches.py:6-22 (patch_presence already reports untracked_files)`; `packages/vmn-exp/src/vmn_exp/ui/readers/baselines.py:88-94 (base only when has_patch)`; `packages/vmn-exp/webui/src/components/RunChanges.tsx:17, 42-47 (no chosen baseline gives the clean-tree text)`; `packages/vmn-exp/webui/src/components/runChangesBaseline.ts:36-40 (defaultBaseline prefers `base` over `previous`)`; `packages/vmn-exp/tests/test_ui_run_baselines_api.py:45-52 (pins base for a patch run and no base for a clean run; neither is untracked-only)`

<a id="b5a"></a>
### B5a. Move the experiment flags into per-group modules with an audited action-to-flag table (no behaviour change)

P2 · L · after B6, plan 38 A4 and plan 42 E1

**Problem.** The `experiment` command is one argparse parser with about 60 flags shared by 25 actions, defined in a single 200-line function inside a 563-line plugin.py. Help text carries `list/show/...:` prefixes because nothing else says which action a flag belongs to. No data structure records flag ownership, so nothing can reject or hide a flag that an action ignores.

**Approach.**

New package `cli/exp_parser/` with small files: `flags_select.py` (-v, --latest, --last, --query, --archived, --json), `flags_create.py`, `flags_run.py`, `flags_list.py`, `flags_prune.py`, `flags_rerun.py`, `flags_mlflow.py`, `flags_storage.py`, `flags_misc.py`. Each exposes `add_<group>(parser)`. The existing add_* helpers (define_metric_args, finish_args, intent_arg, similar_args, sweep storage flags) become groups as they are.

`actions.py` holds `ACTION_FLAGS = {action: (group, ...)}`. The table is derived from an audit of what each of the 25 handlers reads (`args.x` and `getattr(args, "x")` in its module and callees), not from the help prefixes, which are known to be incomplete. Storage, writer-id and from-snapshot flags belong to every action that opens a store. Record the audit as a table in this file. The audit runs after B6 (`--json` on `compare`), plan 38 A4 (`--no-adopt` on `run`) and plan 42 E1 (the long-form flags the UI job builder emits) have landed, so those flags are in the table from the start; a flag another plan adds later adds its own table entry in the same commit.

`_add_experiment_parser` moves to `exp_parser/build.py` and still builds the same flat parser by applying every group once. `plugin.py` keeps only registration.

**Tests first.**

- packages/vmn-exp/tests/test_exp_parser_characterization.py (unit, parse_user_commands after register_all, no repo): a corpus of about 40 real argv lines taken from docs/vmn-exp/experiments.md, client-guide.md and cli/skill.py, asserting the parsed Namespace. Written and green against today's parser before the move, then kept green.
- packages/vmn-exp/tests/test_exp_parser_actions.py: test_every_flag_of_the_flat_parser_belongs_to_exactly_one_group (red until the groups exist); test_every_action_has_a_flag_tuple; test_every_group_is_used_by_some_action; test_every_corpus_line_uses_only_flags_its_action_owns

**Files.** `packages/vmn-exp/src/vmn_exp/cli/exp_parser/__init__.py`, `packages/vmn-exp/src/vmn_exp/cli/exp_parser/actions.py`, `packages/vmn-exp/src/vmn_exp/cli/exp_parser/build.py`, `packages/vmn-exp/src/vmn_exp/cli/exp_parser/flags_*.py`, `packages/vmn-exp/src/vmn_exp/cli/plugin.py`, `packages/vmn-exp/tests/test_exp_parser_characterization.py`, `packages/vmn-exp/tests/test_exp_parser_actions.py`

**Risk.** The move itself is mechanical and guarded by the corpus. The real work and risk is the ownership audit: a flag wrongly left out of an action's tuple becomes a rejected command in B5b. Help-reading tests (test_docs_similar_statements.py:80-86, test_exp_backend_removed.py:80-85, test_exp_show_patch_args.py:45) read the flat `--help`. They need every flag still present, `--note NOTE` still printed after `-v VERSION, --version VERSION` (plugin.py:78, 84), and the `-v` and `--max-bytes` help text unchanged. Apply the groups in an order that keeps that, and move no help string in this item. test_architecture_boundary.py and test_packaging_split.py classify modules by glob; confirm the new package falls under the `vmn_exp/cli` globs.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/plugin.py:32-45 (25 EXPERIMENT_ACTIONS)`; `packages/vmn-exp/src/vmn_exp/cli/plugin.py:48-253 (_add_experiment_parser: one flat parser, prefixed help strings)`; `packages/vmn-exp/src/vmn_exp/cli/plugin.py:165-166 (`--json` help lists list/show/importance/push/similar; lineage.py:62 and rerun.py:60 also honour it)`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:327-416 (dispatch; handlers read args.sort, args.top, getattr(args, ...) directly)`; `grep: `_add_experiment_parser` is referenced only in plugin.py (no test imports it)`

<a id="b5b"></a>
### B5b. Reject flags an experiment action does not own (exit 2), on the unchanged flat parser; ships with B5d

P2 · M · depends on B5a and plan 42 E1 · same release as B5d

**Problem.** Because every flag is valid on every action, `vmn-exp list app --force --local-only --yes` parses silently and the flags are ignored. A flag-shaped token in any argv built by a program lands on whichever of 60 flags it names.

**Approach.**

Keep the flat parser exactly as it is, so every argv that parses today parses identically (implicit `create`, flags before the action, prefix abbreviations, `exp --help`). No argparse subparsers.

New pure function `exp_parser/ownership.py: foreign_flags(args, action, defaults, action_flags)`: the option strings whose parsed value differs from the parser default and whose group is not in `ACTION_FLAGS[action]`. `defaults` and the flag-to-group map are read from a throwaway flat parser that `exp_parser/build.py` builds for the call (`parser.get_default`); the handler never sees the parser core built, and a default such as `--max-bytes` reads a module value when the parser is built (plugin.py:154-157), so the two must be built the same way at the same time. A foreign flag passed with its default value changes nothing and is indistinguishable from not passing it, so it is not reported.

Call it first in `handle_experiment` (before `auto_init` and before opening storage) and first in `_exp_run_without_repo`: log `'--force' is not a flag of 'vmn-exp list' (see 'vmn-exp list --help')` and return 2. The help it points at is B5d's, which is why the two ship in one release. `refuse_stray_refs` stays as it is.

It is a hard error from the release that ships it. There is no warning release.

The UI job builder is the one program that writes these argv lines. After plan 42 E1 every request-derived option it emits is a long-form `--flag=value` token from one builder (metrics are one `--metrics=<k>=<v>` token per metric, which E1's first commit makes the parser accept with `action="extend"`), and E1's fuzz test walks an `ACTIONS` list. One test here builds each UI action's argv from a benign body, skips the `vmn stamp`, `vmn release` and `vmn goto` lines (they are not experiment actions), parses the rest, and asserts `foreign_flags` is empty.

**Tests first.**

- packages/vmn-exp/tests/test_exp_flag_ownership.py (unit, SimpleNamespace + plain dicts): test_a_prune_flag_on_list_is_foreign; test_an_owned_flag_is_not_foreign; test_a_flag_left_at_its_default_is_not_reported; test_storage_flags_are_owned_by_every_store_action; test_several_foreign_flags_are_all_named
- packages/vmn-exp/tests/test_exp_flag_ownership.py (handler level, LocalSnapshotStorage on tmp_path, vcs=None via _exp_run_without_repo): test_list_with_force_exits_2_and_touches_nothing; test_create_with_latest_exits_2_before_any_record_is_written; test_the_error_names_the_flag_the_action_and_its_help
- packages/vmn-exp/tests/test_exp_flag_ownership.py (unit, the in-repo dispatch point: `handle_experiment` called with a `SimpleNamespace(vcs=None, args=...)` context; the check runs before anything reads `vcs`): test_handle_experiment_rejects_a_foreign_flag_before_touching_the_repo
- packages/vmn-exp/tests/test_exp_flag_ownership.py (unit, build_command + parse_user_commands, no repo): test_no_ui_job_argv_carries_a_foreign_flag (parametrized over the action list plan 42 E1's fuzz test uses)
- packages/vmn-exp/tests/test_exp_parser_characterization.py: every B5a corpus line still returns 0 foreign flags

**Files.** `packages/vmn-exp/src/vmn_exp/cli/exp_parser/ownership.py`, `packages/vmn-exp/src/vmn_exp/cli/experiment.py`, `packages/vmn-exp/src/vmn_exp/cli/plugin.py`, `packages/vmn-exp/tests/test_exp_flag_ownership.py`, `docs/vmn-exp/experiments.md`, `docs/vmn-exp/upgrading.md` (row), `packages/vmn-exp/src/vmn_exp/cli/skill.py`, `docs/vmn-exp/agent-skill.md (regenerated)`

**Risk.** Commands that pass a flag the action ignores today fail with exit 2; this ships in a 0.1.x patch release and needs an `upgrading.md` row that names the rule and the message. The whole exp suite drives the CLI through `_experiment` (exp_helpers.py:28-90), so it is the widest corpus available: a test that starts failing names either a wrong table entry (fix the table) or a genuinely ignored flag. The second kind is a test edit this plan cannot name in advance, so the repo rule applies to it: stop and ask. Also sweep packages/vmn-exp/tests/uiload and the `ui/jobs*.py` argv builders. Nothing that parses today stops parsing; rejection happens in the handler, so test_experiment.py:471-476 stays green. If plan 42 E1 has not landed when this starts, the UI test is written against today's `build_command` actions and re-pointed at E1's action list afterwards.

**Owner decision (2026-11-11).** Exit 2 for a flag the action does not own, shipped together with per-action `--help` (B5d). No argparse subparsers.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/plugin.py:60-70 (action nargs="?" default create; name; refs nargs="*" on every action)`; `packages/vmn-exp/src/vmn_exp/cli/manage.py:30-36 (refuse_stray_refs: the existing post-parse rejection pattern)`; `packages/vmn-exp/src/vmn_exp/cli/experiment.py:327-355 and cli/plugin.py:374-448 (the two dispatch points: handle_experiment and _exp_run_without_repo)`; `packages/vmn-exp/src/vmn_exp/ui/jobs.py:75-165 (build_command: the argv lines the server writes today)`; `packages/vmn-exp/tests/test_experiment.py:471-476 (parse_user_commands(["experiment", "--latest", "my_app"]) must parse; it bypasses main._to_vmn_argv)`; `packages/vmn-exp/tests/test_exp_backend_removed.py:80-85 (`exp --help` must contain `--bucket`)`; `17 exp test files call parse_user_commands directly (e.g. test_storage_store_flags.py:45, test_docs_import_mlflow_examples.py:58, test_cli_exp_import_mlflow_refresh.py:73)`

<a id="b5d"></a>
### B5d. `vmn-exp <action> --help` lists only that action's flags; ships with B5b

P2 · M · depends on B5a, B1 · same release as B5b

**Problem.** `vmn-exp list --help` prints all 60 experiment flags, with `list/show:` prefixes as the only hint of what applies. After B5a the ownership table exists, but help still comes from the flat parser. Once B5b rejects a foreign flag, the user needs a help page that says which flags the action does own.

**Approach.**

Help only; parsing stays on the flat parser. No argparse subparsers.

New `exp_parser/help.py` with two functions:
- `help_action(vmn_argv)` (pure): the action name when the argv, after an optional leading `--debug`, starts with `exp` or `experiment`, its next token is one of `EXPERIMENT_ACTIONS`, and `-h` or `--help` appears before any `--`. Otherwise None. A flag placed before the action (`vmn-exp exp --json list --help`) gives None and so the full help, as today.
- `action_parser(action)`: an `argparse.ArgumentParser(prog=f"vmn-exp {action}")` with the `name` and `refs` positionals and only the groups in `ACTION_FLAGS[action]`. It is built on each call, not at import, because a flag's help reads module values at build time (`--max-bytes` prints `views.PATCH_MAX_BYTES`).

In `vmn_exp_run`, after B1's argv normalization and `register_all()`, when `help_action` names an action: `action_parser(action).print_help()` and `raise SystemExit(0)`, which is how argparse itself leaves `--help`, so callers that expect the exit keep working. `vmn-exp exp --help` and `vmn-exp --help` are unchanged (the full list).

In a second commit, help strings drop their `list/show:` prefixes, and the full `exp --help` groups flags with argparse argument groups named after the flag modules.

**Tests first.**

- packages/vmn-exp/tests/test_exp_action_help.py (pure, help_action): test_an_action_with_help_names_the_action; test_help_after_a_double_dash_belongs_to_the_child; test_exp_help_without_an_action_is_the_full_help; test_debug_before_the_action_is_skipped; test_a_bare_app_name_is_not_an_action
- packages/vmn-exp/tests/test_exp_action_help.py (unit, in-process vmn_exp_run with capsys, no repo): test_list_help_names_sort_and_not_keep; test_action_help_usage_reads_vmn_exp_action; test_action_help_exits_0_like_argparse; test_exp_help_still_lists_every_flag; test_every_action_has_help (parametrized over EXPERIMENT_ACTIONS)
- Approved test edit, packages/vmn-exp/tests/test_docs_similar_statements.py:80-86 (`_version_help`): the slice of `similar --help` still starts at `-v VERSION, --version VERSION`; its end anchor changes from `--note NOTE` (a flag `similar` does not own) to the next option entry in `similar`'s own help. The assertion that the `-v` help carries the no-ref sentence is not changed.

**Files.** `packages/vmn-exp/src/vmn_exp/cli/exp_parser/help.py`, `packages/vmn-exp/src/vmn_exp/cli/main.py`, `packages/vmn-exp/src/vmn_exp/cli/exp_parser/flags_*.py`, `packages/vmn-exp/tests/test_exp_action_help.py`, `packages/vmn-exp/tests/test_docs_similar_statements.py`, `docs/vmn-exp/experiments.md`, `docs/vmn-exp/upgrading.md` (same row as B5b)

**Risk.** Which option follows `-v` in `similar`'s help depends on B5a's table, so the new end anchor is chosen when B5a is done. test_exp_show_patch_args.py:45 runs `vmn-exp exp show app -v 0.0.1 --help` under a patched `views.PATCH_MAX_BYTES` and expects `(default: 4242)` with exit 0; it stays green only because `action_parser` builds the flags at call time and `show` owns `--max-bytes`. test_exp_backend_removed.py:80-85 reads `exp --help`, which keeps every flag. Dropping the `list/show:` prefixes changes help text everywhere: grep the suites for the prefixed strings first; a test that pins one is not named here, so stop and ask before editing it, and keep that commit separate so it can wait. Callers of `parse_user_commands` directly still get the flat help on `--help`; only the `vmn-exp` command gets per-action help.

**Owner decision (2026-11-11).** Do it, as help-only filtering, in the same release as B5b. No argparse subparsers.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/plugin.py:56-58 (one parser, one help)`; `packages/vmn-exp/src/vmn_exp/cli/plugin.py:154-157 (`--max-bytes` help formats views.PATCH_MAX_BYTES when the parser is built)`; `packages/vmn-exp/src/vmn_exp/cli/main.py:24-46 (vmn_exp_run: where the help request is caught)`; `packages/vmn-exp/tests/test_docs_similar_statements.py:80-86 (runs vmn_exp_run(["similar", "--help"]) under pytest.raises(SystemExit), code 0, and slices between `-v VERSION, --version VERSION` and `--note NOTE`)`; `packages/vmn-exp/tests/test_exp_show_patch_args.py:21-27, 43-47 (`_exp("app", action="show", ..., extra_args=["--help"])`, accepts a return code or SystemExit)`; `packages/vmn-exp/tests/exp_helpers.py:89-94 (`_exp` goes through vmn_exp_run)`; `packages/vmn-exp/tests/test_exp_backend_removed.py:80-85 (`exp --help` must list `--bucket`)`

<a id="b6"></a>
### B6. `--json` on `compare` and `comments`; accurate `--json` help

P2 · S · depends on B2 · lands before B5a

**Problem.** Scripts cannot read `compare` or a comment thread without scraping text: `experiment_compare` and `comments_run_without_repo` only print. The shared `--json` help names five actions although lineage and rerun also honour it.

**Approach.**

New `cli/compare_view.py` with a pure `compare_payload(experiments, schema)` returning `{"runs": [{verstr, metrics, metric_policy}], "metrics": [ordered keys], "params": [...], "conflicts": {key: text}}`, plus the table printer moved out of experiment.py. `experiment_compare` prints `dumps(payload)` under `--json` and no table or diff hint.

`comment.py`: `--json` on `comments` prints the thread as stored (id, ts, author, reply_to, deleted, text; text omitted when deleted); on `comment` it prints `{"id": ...}`. Both reuse `cli.views.dumps`. `comment` and `comments` are their own commands with their own parsers, so the flag is added there, not to the experiment parser.

Fix the experiment `--json` help string to name every action that honours it, `compare` included. B5a's audit, which comes after this item, records `compare` as an owner of `--json`.

No other action gains `--json` here (see Non-goals).

**Tests first.**

- packages/vmn-exp/tests/test_cli_compare_json.py (unit, plain bundles): test_compare_payload_orders_schema_metrics_first; test_compare_payload_names_policy_conflicts; test_compare_payload_separates_params
- packages/vmn-exp/tests/test_cli_compare_json.py (LocalSnapshotStorage, tmp_path): test_compare_json_prints_strict_json_and_no_table
- packages/vmn-exp/tests/test_cli_comments_json.py (LocalSnapshotStorage): test_comments_json_lists_the_thread; test_comment_json_prints_the_new_id; test_a_deleted_comment_keeps_its_flag_and_no_text

**Files.** `packages/vmn-exp/src/vmn_exp/cli/compare_view.py`, `packages/vmn-exp/src/vmn_exp/cli/experiment.py`, `packages/vmn-exp/src/vmn_exp/cli/comment.py`, `packages/vmn-exp/src/vmn_exp/cli/plugin.py`, `packages/vmn-exp/tests/test_cli_compare_json.py`, `packages/vmn-exp/tests/test_cli_comments_json.py`, `docs/vmn-exp/experiments.md`, `docs/vmn-exp/reports.md`

**Risk.** Additive. The JSON shapes become a contract once shipped, so they are kept to fields the store or the existing `show --json` already exposes. Moving the compare printer must keep test_metric_policy_cli_compare.py and test_compare_goal_conflict.py green. Plan 44 G15 later moves the rest of `cli/experiment.py`; it keeps `cli/compare_view.py` as the compare module.

**Owner decision (2026-11-11).** `--json` on `compare` and `comments` only.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/experiment.py:1044-1091 (compare: print only, never reads args.json)`; `packages/vmn-exp/src/vmn_exp/cli/comment.py:18-31, 41-61 (add_comment_parser, add_comments_parser and both handlers: no --json)`; `packages/vmn-exp/src/vmn_exp/cli/plugin.py:165-166 (help text)`; `packages/vmn-exp/src/vmn_exp/cli/lineage.py:62 and cli/rerun.py:60 (already honour --json)`

<a id="b7"></a>
### B7. Document the exit-code contract; the remaining handler-detected usage errors return 2

P3 · S · after B5b

**Problem.** A script cannot tell "you called it wrong" from "it failed". argparse errors exit 2 and the ui verbs already return 2 for a bad invocation, but three experiment-side sites return 1 for the same kind of mistake, and nothing in docs/vmn-exp/experiments.md states the contract.

**Approach.**

Document in experiments.md, as the whole contract:
- 0: success.
- 1: the command ran and failed (not found, store error, refused).
- 2: the invocation was wrong (argparse errors, a flag the action does not own after B5b, a missing required argument).
- `run`, `rerun` and `sweep agent` return the child's code (128+N on a signal). A child that exits 2 cannot be told from a usage error; the doc says so.

No other codes are added.

Change the three handler-detected usage errors that return 1 to 2:
- missing `-f` in `settings set`;
- missing command after `--` in `run`;
- positional refs on an action that takes none (`refuse_stray_refs`, experiment.py:354-355). Its call moves up to sit right after B5b's foreign-flag check at the top of `handle_experiment`, so both usage checks run before auto-init and before a store is opened. `_exp_run_without_repo` does not call it today and is not changed.

Use the literal 2 as the existing sites do; no constants module.

**Tests first.**

- packages/vmn-exp/tests/test_cli_exit_codes.py (unit, direct handler calls with SimpleNamespace args and an in-memory or tmp_path store; no git, no Docker): test_settings_set_without_a_file_is_a_usage_error; test_run_without_a_command_is_a_usage_error; test_stray_refs_are_a_usage_error (`handle_experiment` with a `SimpleNamespace(vcs=None, args=...)` context, as in B5b); test_a_missing_run_is_a_failure_not_a_usage_error

**Files.** `packages/vmn-exp/src/vmn_exp/cli/settings.py`, `packages/vmn-exp/src/vmn_exp/cli/run.py`, `packages/vmn-exp/src/vmn_exp/cli/experiment.py`, `packages/vmn-exp/tests/test_cli_exit_codes.py`, `docs/vmn-exp/experiments.md`, `docs/vmn-exp/upgrading.md` (row)

**Risk.** A wrapper that checks `== 1` for these three mistakes sees 2 instead; that is the `upgrading.md` row. With stray refs checked before the store opens, a command that has both stray refs and a bad store now reports the refs. Before changing, grep the suite for tests asserting 1 on `run` without a command, `settings set` without `-f` or stray refs; none was found for the three error strings ("Unexpected arguments" appears in no test), but rerun_helpers.py and test_exp_intent_cli.py drive `run` and must be re-run. Such a test is not named here, so if one turns up, stop and ask. Commands other plans add (plan 40 C6's `buffers`) follow the same table.

**Owner decision (2026-11-11).** Exit codes stay 0/1/2 plus the child's code, and the contract is documented.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/main.py:45, ui/cli.py:250-253, ui/cache_cli.py:84-86, ui/backup_cli.py:69-70, ui/diag_cli.py:35-37 (usage errors already returning 2)`; `packages/vmn-exp/src/vmn_exp/cli/settings.py:36-39 ("settings set needs -f <file>" returns 1)`; `packages/vmn-exp/src/vmn_exp/cli/run.py:225-230 ("No command to run. Usage: ..." returns 1)`; `packages/vmn-exp/src/vmn_exp/cli/manage.py:30-36 and cli/experiment.py:354-355 (refuse_stray_refs logs "Unexpected arguments for 'exp <action>'" and handle_experiment returns 1, after the store is opened at 346-350)`; `packages/vmn-exp/src/vmn_exp/cli/run.py:213-218 (run returns the child's code, 128+N on a signal)`

<a id="b8"></a>
### B8. `vmn-exp ui` maintenance verbs become real subcommands with their own flags

P2 · M · after plan 42 E4, E2, E5a, E3 in `ui/cli.py`; before plan 44 G7

**Problem.** `vmn-exp ui` takes `cache resync|rebuild`, `onboarding`, `backup <path>` and `diag` as a free positional list on the serve parser, and the flags of all five modes share one namespace. `vmn-exp ui --pid 3` or `vmn-exp ui onboarding --port 1` parses and the stray flag is ignored. `ui --help` shows diag and onboarding flags beside server flags, and an unknown verb is only caught by hand after parsing.

**Approach.**

Move the parser to a new `ui/cli_parser.py`. `ui` keeps serving by default and gains optional subparsers:
- `cache {resync,rebuild}` with `--workspace`
- `onboarding` with `--edits --format --account-id --external-id --origin`
- `backup <path>`
- `diag` with `--url --pid --wait --summarize -o`

The subparsers produce `args.ui_args` themselves, because tests read it straight from the parser and core's `parse_user_commands` offers no post-parse hook: the `ui` parser sets `ui_args=[]`; `diag` and `onboarding` use `set_defaults(ui_args=["diag"])`; `cache` and `backup` take their positional through a small argparse Action that stores `[verb, value]`. A missing `backup` path or `cache` verb stores `[verb]`, so the handlers' own usage messages (exit 2) still fire. The four handlers and `_ui_run_without_repo` are unchanged.

Serve-only flags (`--host --port --allowed-host --read-only --no-browser --no-index --keep-warm --metrics-ended-hours --diag-every`) stay on the `ui` parser only.

The source flags the verbs need (`--config --db --data-dir --token --store --repo`) are added by one function to the `ui` parser with their real defaults and to each verb without a default under `argument_default=argparse.SUPPRESS`. Both `ui --config s.yml cache rebuild` and `ui cache rebuild --config s.yml` then work, and a verb never overwrites a value given before it.

**Tests first.**

- packages/vmn-exp/tests/test_ui_cli_parser.py (unit, bare argparse subparsers, no repo): test_bare_ui_serves_with_empty_ui_args; test_cache_rebuild_with_workspace_gives_todays_ui_args; test_backup_path_gives_todays_ui_args; test_backup_without_a_path_still_reaches_the_handlers_usage_error; test_config_before_or_after_the_verb_is_the_same; test_a_verb_does_not_reset_a_flag_given_before_it; test_diag_flags_are_rejected_when_serving (SystemExit 2); test_serve_flags_are_rejected_on_onboarding; test_an_unknown_verb_is_an_argparse_error; test_ui_help_lists_the_verbs_and_no_diag_flags
- packages/vmn-exp/tests/test_ui_cli_parser.py: test_diag_still_runs_without_a_repo (via _ui_run_without_repo with a fake handler)

**Files.** `packages/vmn-exp/src/vmn_exp/ui/cli_parser.py`, `packages/vmn-exp/src/vmn_exp/cli/plugin.py`, `packages/vmn-exp/src/vmn_exp/ui/cli.py`, `packages/vmn-exp/tests/test_ui_cli_parser.py`, `docs/vmn-exp/ui.md`, `docs/vmn-exp/server.md`, `docs/vmn-exp/byo-bucket.md`, `docs/vmn-exp/upgrading.md` (row)

**Risk.** Invocations that put a verb's flag before the verb (`vmn-exp ui --url X diag`) stop parsing, and a stray flag of another mode is now an argparse error (exit 2), which is the `upgrading.md` row; the documented forms and cli/skill.py put them after. `-o/--output` and `--format` exist only on their verbs. A verb name can no longer be the value of nothing: `vmn-exp ui cache` with no verb reaches the handler's usage error as today. Pinned tests that must stay green untouched: test_ui_cache_cli.py:41-43, test_ui_backup_cli.py:24, test_ui_diag_cli.py, test_ui_onboarding_cli.py, test_ui_cli.py, test_storage_store_flags.py:40-46 and 86-88, test_ui_keep_warm_config.py, test_ui_metrics_feed_config.py. Import boundary: plugin.py imports the ui parser lazily, as it does `vmn_exp.cli.views` today.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/plugin.py:256-332 (_add_ui_parser: `ui_args` nargs="*" plus serve, cache, onboarding and diag flags on one parser)`; `packages/vmn-exp/src/vmn_exp/ui/cli.py:236-256 (handle_ui dispatches on args.ui_args[0]; unknown verb returns 2 by hand)`; `packages/vmn-exp/src/vmn_exp/ui/cache_cli.py:82-86 and ui/backup_cli.py:67-70 (handlers read args.ui_args[1:])`; `packages/vmn-exp/src/vmn_exp/cli/plugin.py:359-367 (_ui_run_without_repo reads ui_args[0] == "diag")`; `packages/vmn-exp/tests/test_ui_cache_cli.py:17-20, 41-43 and test_ui_backup_cli.py:20-24 (read args.ui_args straight from parse_user_commands, with `--data-dir` placed after the verb)`; `packages/vmn-exp/tests/test_ui_diag_cli.py:25-28, test_ui_onboarding_cli.py:20, test_ui_cli.py:10-149, test_storage_store_flags.py:40-46, 86-88 (other direct parses of `ui`)`

<a id="b9a"></a>
### B9a. Record where `vmn-exp run` spends its time and pin the git-process cost with budget tests

P2 · S · lands before plan 38 A5

**Problem.** Nobody had measured the wrapper's overhead, and nothing stops it growing. Measured for this plan in a scratch clone (local store, Python 3.12, 206 installed packages): `run -- true` 0.47 s wall; `run -- python -c pass` 1.02 s; `run -- sleep 0.3` 1.00 s; a 5-metric SDK script 0.43 s alone and 1.0 s wrapped. `--debug` for the no-op: vmn_run 0.29 s, of which stamper init 0.09 s and experiment_run 0.17 s; the remaining ~0.2 s of wall is interpreter start and imports. SDK `start_run` 0.32 s, of which `gitmode.checkout_source` 0.30 s (tracked_vcs 0.22 s, about 15 git subprocesses 0.16 s). The env probe costs at most 0.05 s (1.03 s with, 0.99 s with `--no-env`). The reported 5 s for a 1.5 s job was not reproduced in absolute terms; the ratio was.

**Approach.**

1. The measured table is in this file's Summary, with the commands that produced it, so later changes have a baseline. B9d adds the numbers taken after adoption.
2. New test helper `packages/vmn-exp/tests/git_budget.py` with a pure `summarize(calls)`: one line per git subcommand with its count, most frequent first, then the argv lists. Budget failures print it, and B9d's argv list is its output.
3. Add git-process budget tests in the style of tests/test_git_process_budget.py, counting git argv through the same two patch points (`git.cmd.Git.execute`, `git_cmd.subprocess.run`): one bound for `vmn-exp run <app> -- true` on an initialised app, one for SDK `start_run` on an initialised app, one for the second of two consecutive `start_run` calls. Bounds are set from the measured counts plus a small margin.
4. No new timing module: `--debug` already prints per-function times. No wall-clock assertion: it measures machine load, and the repo's timing benchmarks are a separate serial pass.

**Tests first.**

- packages/vmn-exp/tests/test_git_budget_summary.py (unit, plain argv lists, no git): test_summary_counts_calls_per_git_subcommand; test_summary_lists_the_most_frequent_subcommand_first; test_summary_of_no_calls_is_empty
- packages/vmn-exp/tests/test_exp_run_git_budget.py (second tier by nature: real git repo fixture, as test_git_process_budget.py is; its `git_calls` fixture copied from there): test_run_of_a_noop_command_costs_at_most_N_git_processes; test_sdk_start_run_costs_at_most_N_git_processes; test_a_second_start_run_costs_no_more_than_the_first

**Files.** `packages/vmn-exp/tests/git_budget.py`, `packages/vmn-exp/tests/test_git_budget_summary.py`, `packages/vmn-exp/tests/test_exp_run_git_budget.py`, `docs/plans/39-vmn-exp-cli-surface.md` (the counts)

**Risk.** Tests only. The bounds are counts, so they do not flake under xdist load. The budget tests pin today's cost, so they pass on arrival; they are a regression guard and the measuring stick for B9d, not a red-green pair. The red-green pair in this item is the summary helper. Plan 38 A5 changes what a `start_run` inside `vmn-exp run` does (it adopts instead of capturing), which is why the bounds here are taken in-process, outside a supervisor, and why this lands before A5.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/run.py:235-257 (create, intent, inputs, lock release, similar hint, then supervision)`; `packages/vmn-exp/src/vmn_exp/gitmode/checkout.py:39-65 (checkout_source: tracked_vcs, capture_snapshot, env, ensure_code, capture_features)`; `packages/vmn-exp/src/vmn_exp/gitmode/coldstart.py:20-52 (build_vcs constructs a full VersionControlStamper per start_run)`; `packages/vmn/src/version_stamp/core/logging.py:95-125 (measure_runtime_decorator: the per-function table under --debug already exists)`; `tests/test_git_process_budget.py:1-60 (git_calls fixture and count-based bounds: the style to follow)`

<a id="b9b"></a>
### B9b. Supervision loop wakes when the child exits instead of sleeping a fixed 0.5 s

P1 · S · after plan 38 A4; before plan 44 G8

**Problem.** After the child exits, `vmn-exp run` stays in `time.sleep(0.5)` until the poll interval ends. Measured: `run -- true` 0.47 s but `run -- python -c pass` 1.02 s and `run -- sleep 0.3` 1.00 s, so up to 0.5 s of pure wait on every run and every sweep trial. It is the largest removable part of the overhead. The loop calls `time.monotonic`/`time.sleep` directly, so no unit test can observe it.

**Approach.**

New module `cli/supervise_loop.py` (run.py is 539 lines; this moves code out): a pure `watch(child_exited, wait_child, tick, clock, interval)` that runs `tick(now)` at most once per interval while the child lives and returns as soon as `wait_child(timeout)` reports the exit. The body of today's loop (ingest, sync request, heartbeat, sampler, on_tick, enforce_grace) becomes the `tick` callable built in `_Supervision._supervise`.

`_Supervision` wires the real IO in one place: `clock=time.monotonic`, `wait_child` = `proc.wait(timeout=...)` catching `subprocess.TimeoutExpired`. Its constructor signature does not change, so rerun, the sweep agent and the three direct test constructions are untouched. The loop logic itself holds no real IO.

**Tests first.**

- packages/vmn-exp/tests/test_supervise_loop.py (unit: FakeClock advanced by a fake wait_child, no process, no real sleeping): test_the_loop_returns_at_the_childs_exit_time_not_the_next_interval; test_tick_runs_once_per_interval_while_the_child_lives; test_a_child_that_has_already_exited_gets_no_wait; test_tick_receives_the_injected_clocks_time; test_no_wait_is_requested_after_the_child_has_exited

**Files.** `packages/vmn-exp/src/vmn_exp/cli/supervise_loop.py`, `packages/vmn-exp/src/vmn_exp/cli/run.py`, `packages/vmn-exp/tests/test_supervise_loop.py`

**Risk.** Low. `Popen.wait(timeout)` polls internally with short sleeps, so Python-level signal handlers still run and `forwarder.enforce_grace` still runs once per interval. test_fix_exp_run_signals.py, test_fix_exp_run_supervisor.py, test_exp_rerun_signals.py and test_exp_rerun_recording.py cover the loop's signal and recording behaviour and must stay green untouched. Metrics written in the child's last instants are still ingested by `_finish` (run.py:425). `_Supervision` still picks the real clock itself rather than receiving it from main; moving that wiring up to the entry point is plan 44 G8, which injects io into this `watch()` and its tick rather than extracting a second loop. Plan 38 A4 extracts `supervised_env` from `_Supervision._start` and adds a keyword-only `adopt`; it lands first, so this item rebases onto it and leaves `_start` alone.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/run.py:46 (_METRICS_TAIL_INTERVAL = 0.5)`; `packages/vmn-exp/src/vmn_exp/cli/run.py:379-397 (`while proc.poll() is None: ... time.sleep(_METRICS_TAIL_INTERVAL)`)`; `packages/vmn-exp/src/vmn_exp/cli/run.py:269-287 (_Supervision.__init__ signature)`; `packages/vmn-exp/src/vmn_exp/cli/rerun.py:159 and cli/sweep/agent.py:99 (the other two production callers)`; `packages/vmn-exp/tests/test_exp_rerun_recording.py:140, 155, 165 (tests construct _Supervision directly with today's signature)`

<a id="b9d"></a>
### B9d. Re-measure the SDK repo capture after adoption (plan 38 A5, A12), then trim redundant git calls

P2 · M · depends on B9a, plan 38 A5 and A12

**Problem.** Inside `vmn-exp run` the script's `start_run` is auto-parented by `VMN_EXPERIMENT_ID` and goes through the full checkout-mode record source again. Profiled: `start_run` 0.32 s, of which `checkout_source` 0.30 s: a fresh VersionControlStamper (about 15 git subprocesses, 0.16 s), repo status, identity capture, plus about 0.09 s importing `version_stamp.stamping` and GitPython. The supervisor did the same work moments earlier (stamper init 0.09 s inside vmn_run, then create). On a larger repo or slower disk each git process costs more, which is the likely source of the reported 3.5 s.

Plan 38 A5 and A12 change this picture. The script that `vmn-exp run`, a rerun or a sweep trial launches directly adopts the wrapper's run through `resume.locate` and never reaches `checkout_source`, so the repeat disappears for the default case. `checkout_source` still runs in full for: a `start_run` with no supervisor (every plain SDK user), `--no-adopt` or `VMN_EXP_ADOPT=0`, a process that is not the supervisor's direct child (a worker a launcher spawned, so every fleet worker), an adoption declined because the child resolved another store, and a second `start_run` in a process that already adopted. Those are the cases this item speeds up.

**Approach.**

1. Re-measure, after A5 and A12 have landed. Re-run the commands of the Summary table and B9a's budget tests, add one budget test for an adopted `start_run`, and write into this file: the new table, and the git argv of one unsupervised `start_run` as `git_budget.summarize` prints it.
2. Mark the redundant calls in that list: a git command whose answer an earlier step of the same `checkout_source` call already holds. The steps, in order, are `build_vcs` (the stamper constructor), `repo_status`, `capture_snapshot` (already handed the status, checkout.py:46-47), `build_storage`, `_maybe_capture_env`, `ensure_code`, `capture_features` and `experiment_conf`.
3. Remove them, one commit per call. Each commit starts with a unit test on a recording fake at the function that issues the duplicate, then the change, then a lower bound in `test_sdk_start_run_costs_at_most_N_git_processes`. Nothing a run records changes.
4. If step 2 finds no redundant call, close the item with the list.

The supervisor's captured identity is not handed to the child and not reused. Adoption removes the case that would have needed it.

**Tests first.**

- packages/vmn-exp/tests/test_exp_run_git_budget.py (second tier, real git; written in step 1): test_an_adopted_start_run_costs_at_most_N_git_processes
- Per trimmed call, first a unit test with no git: packages/vmn-exp/tests/test_gitmode_capture_once.py, one test per call, named `test_<function>_asks_for_<fact>_once`. The fake is a recording stand-in for the object that function receives (`vcs`, or `vcs.backend`) and the test asserts the query is made once across the steps that used to repeat it. A duplicate that sits inside `version_stamp` gets its unit test in core `tests/` instead.
- Then the second-tier red test: the lowered N in packages/vmn-exp/tests/test_exp_run_git_budget.py::test_sdk_start_run_costs_at_most_N_git_processes.

**Files.** `docs/plans/39-vmn-exp-cli-surface.md` (the re-measured table, the argv list, the calls marked redundant), `packages/vmn-exp/tests/test_exp_run_git_budget.py`, `packages/vmn-exp/tests/test_gitmode_capture_once.py`, `packages/vmn-exp/src/vmn_exp/gitmode/coldstart.py`, `packages/vmn-exp/src/vmn_exp/gitmode/checkout.py`, `packages/vmn-exp/src/vmn_exp/gitmode/capture.py`

**Risk.** Which calls are redundant cannot be settled by reading the code: the git commands are issued inside `VersionControlStamper`, `_get_repo_status`, `capture_identity` and `ensure_code`, all reached through `version_stamp.api`, and only the argv list from step 1 shows the repeats. So the unit-test names and the exact files are fixed in step 2, not here, and the size (M) is an estimate. A trim that has to change `version_stamp` backends meets core's own budget test (tests/test_git_process_budget.py) and plan 35's IO migration, which is still only proposed; keep the change on the gitmode side where possible and take the core part as its own commit. The SDK import rule holds: no `version_stamp` in `vmn_exp.sdk`; gitmode is imported lazily. The adopted-run budget test depends on how plan 38 A5 lets a test grant adoption (its `sdk/adoption.py` takes `env` and `getppid` as parameters in the plan); write it against what A5 ships. No recorded data changes, so no `upgrading.md` row.

**Owner decision (2026-11-11).** Re-measure after plan 38 A5 and A12, then trim redundant git calls.

**Evidence.** `packages/vmn-exp/src/vmn_exp/cli/run.py:318-321 (child gets VMN_EXPERIMENT_ID, VMN_APP_NAME, VMN_METRICS_FILE)`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/create.py:107-136 (create_record -> record_source -> gitmode().checkout_source)`; `packages/vmn-exp/src/vmn_exp/gitmode/checkout.py:39-65 (tracked_vcs, capture_snapshot(vcs, status=status), build_storage, env, ensure_code, capture_features, experiment_conf on every start_run)`; `packages/vmn-exp/src/vmn_exp/gitmode/coldstart.py:20-52 (build_vcs builds a VersionControlStamper; tracked_vcs then calls repo_status and returns the status for reuse)`; `packages/vmn-exp/src/vmn_exp/gitmode/capture.py:9-15 (capture_snapshot and ensure_code are version_stamp.api's capture_identity and ensure_code)`; `packages/vmn-exp/src/vmn_exp/cli/rerun.py:159 and cli/sweep/agent.py:99 (the rerun and sweep-trial supervisors plan 38 A12 makes adopt)`; `docs/plans/38-vmn-exp-first-run.md A5 (an adopted run goes through resume.locate, not create_record)`; `cProfile of sdk.start_run in a scratch clone of this repo at 25f03f3d: create_record 0.323 s, checkout_source 0.301 s, tracked_vcs 0.220 s, 16 GitPython execute calls 0.166 s`

## Dropped

<a id="b5c"></a>
- **B5c** (UI job builder validates every value it puts on an argv). Absorbed into [plan 42 E1](42-vmn-exp-server-security-api.md#e1), which the owner decided as the uniform `--flag=value` form for every option through one builder, with the argv-pinning tests rewritten. E1 covers B5c's validators, the dash-leading note and the hostile-value round-trip test. What stays here is one test in B5b: no UI job argv may carry a flag its action does not own.
- **B9c** (skip or cache the env-probe subprocess). Dropped at review: the probe costs at most 0.05 s of a 1.0 s wrap, and the change would have weakened the isolated `-I` capture. Details under "Review findings corrected or dropped".

## Review findings corrected or dropped

- **Finding 5 (part): `--json` is missing on `model`.** Wrong. `vmn-exp model list`, `show` and `resolve` define `--json` (packages/vmn-exp-sdk/src/vmn_exp/registry/cli_parser.py:68, 74, 80).
- **Finding 5 (part): `--json` is missing on `lineage`.** Wrong. `experiment_lineage` honours `--json` (packages/vmn-exp/src/vmn_exp/cli/lineage.py:62). Only the shared flag's help text omits it (packages/vmn-exp/src/vmn_exp/cli/plugin.py:165-166), which B6 corrects. The compare and comment(s) parts are real (B6). `settings show` prints the stored YAML itself (packages/vmn-exp/src/vmn_exp/cli/settings.py:30-34), so no `--json` is planned there.
- **Finding 5 (part): exit codes are only 0/1.** Not exact. Usage errors already exit 2 from argparse, from the stamping-command guard (packages/vmn-exp/src/vmn_exp/cli/main.py:45) and from every ui verb (ui/cli.py:253, ui/cache_cli.py:86, ui/backup_cli.py:70, ui/diag_cli.py:37). `run` returns the child's code, 128+N on a signal (packages/vmn-exp/src/vmn_exp/cli/run.py:213-218). The real gap is an undocumented contract and three sites returning 1 for a usage error (settings.py:36-39, run.py:225-230, experiment.py:354-355); B7 covers that.
- **Finding 7 (hypothesis): import cost explains the `vmn-exp run` overhead.** Ruled out by measurement: `vmn-exp --version` is 0.22 s wall and the whole no-op wrap is 0.47 s. Imports and interpreter start are about 0.2 s of that and are not planned for reduction.
- **Finding 7 (hypothesis) and draft item B9c: the env-probe subprocess is a meaningful part of the overhead.** Ruled out by measurement in a 206-package venv: `vmn-exp run app -- python -c pass` took 1.01-1.04 s with the probe and 0.97-1.01 s with `--no-env`, a difference of at most 0.05 s, below the draft's own 100 ms threshold. B9c is dropped; it would also have traded the isolated `-I` probe (packages/vmn-exp-sdk/src/vmn_exp/core/env.py:265-285) for a less isolated capture.
- **Finding 7 (magnitude): wrapping a 1.5 s job costs about 5 s wall.** Not reproduced in absolute terms. In a scratch clone of this repo (local store, Python 3.12) a 5-metric SDK script took 0.43 s alone and 1.0 s under `vmn-exp run`; a no-op wrap took 0.47 s. The ratio (about 2.3x) matches the report, so the finding is real in proportion. The measured causes are the fixed 0.5 s poll sleep (packages/vmn-exp/src/vmn_exp/cli/run.py:397; B9b) and the nested SDK run repeating the repo capture (packages/vmn-exp/src/vmn_exp/gitmode/checkout.py:39-65; B9d). First-ever run of an app adds a one-off auto-init (1.2 s here).
- **Finding 4 (claim): the flat flag namespace is the root cause of the HTTP argument-injection bug.** Overstated. The cause was `ui/jobs.py` passing request values as separate argv tokens with no check that they are not flag-shaped; that is fixed for metric names in commit 859da19b (packages/vmn-exp/src/vmn_exp/ui/jobs.py:55-72) and plan 42 E1 closes the remaining values (jobs.py:86-161). The flat namespace (packages/vmn-exp/src/vmn_exp/cli/plugin.py:48-253) widens what an injected token can reach from one action's flags to all 60; B5b shrinks that reach. The 1,227-line file, the shared parser and the prefixed help strings are confirmed as stated.
- **Task premise: the `_metric_args` and `storage/buffered.py` fixes are still in flight.** Both are already on master: 859da19b "fix(ui): reject option-like metric names in job actions" and 59becdd5 "fix(sdk): keep the log buffer when the final ship fails". Neither is re-planned; plan 42 E1 builds on the first rather than rebasing around it.

## Non-goals

- Re-planning the two landed fixes: `_metric_args` rejecting names starting with `-` (ui/jobs.py, commit 859da19b) and `storage/buffered.py` keeping the buffer after a failed final ship (commit 59becdd5). The follow-up on the other values in the same builder is plan 42 E1.
- Replacing the experiment flat parser with argparse subparsers, or adding an argv-rewriting hook to core `parse_user_commands`. B5b enforces ownership after parsing and B5d filters help; the owner decided against subparsers.
- Renaming or removing the `exp`/`experiment` command, the bare `vmn-exp <app>` create shortcut, or any existing flag name.
- Changing how numeric params are folded into `metrics` in the index, the row payload, `list --json` or `show --json` (fold.py:255-259). B2 only changes what `show` and `compare` print.
- Changing `vmn-exp list` rows that show `lr=0.25` among the metrics (pinned by test_experiment_params_entry.py:99-106), or regrouping storage-order listings into true trees (pinned by test_fix_cli_exp.py:138-144).
- Showing the contents of untracked files in the Changes card or in `show --patch`, or including untracked files in the run-to-run diff (`experiments-diff`). B4 names them and says how to get them back.
- `--json` for diff, watch, prune, compact, settings or model register/alias, and a machine-readable error format on stderr.
- Exit codes beyond 0/1/2 and the child's code.
- Shell completion for `vmn-exp` (the root `--completion*` flags keep describing vmn), core error strings that say `vmn` when reached through vmn-exp (entry.py:293), and any change to what `vmn --help` or `vmn --version` print.
- Splitting `cli/experiment.py` (1,227 lines) or `cli/run.py` (539 lines) beyond what an item moves (the compare view, the parser, the supervision loop). The rest goes through the boy scout rule as separate commits, including deduplicating the supervision flags in `cli/sweep/parser.py:43-63`.
- Reducing interpreter start and import time (about 0.2 s), the stamper init inside `vmn_run` (0.09 s), or the env probe (at most 0.05 s).
- Lowering default heartbeat or sync intervals, changing what a run captures, or making `vmn-exp run` skip any recorded data to save time. B9 removes waiting and repeated work only.
- A wall-clock budget test or a new phase-timing module. `--debug` already prints per-function times; the budget tests count git processes.
- Turning `vmn-exp ui` maintenance verbs into top-level commands; they stay under `ui`.
- Migrating every existing direct `time`/`subprocess`/`os.environ` call in the CLI to injected IO. Only the code these items touch is migrated (the supervision loop in B9b, the version reader in B1).

## What the critic changed in the draft

- B5b redesigned. The draft's per-action subparsers put argv normalization in `main._to_vmn_argv`, but 17 exp test files call `parse_user_commands` directly. `test_experiment.py:471-476` (`["experiment", "--latest", "my_app"]`), `test_docs_similar_statements.py:80-86` (`similar --help` must contain `--note NOTE`) and `test_exp_backend_removed.py:80-85` (`exp --help` must contain `--bucket`) would all break, and the draft named none of them. B5b now keeps the flat parser and rejects foreign flags after parsing with a pure `foreign_flags` function at the two dispatch points; nothing that parses today stops parsing. Size L to M. The `ALL_DEFAULTS` trick, the deletion of `refuse_stray_refs` and the sweep-flag reuse were dropped (the last moved to the boy-scout non-goal).
- B5d added for per-action `--help`, the one benefit the subparser design had that B5b does not. It is help-only and names the test whose anchor must change.
- B5a kept but resized M to L and re-scoped: the action-to-flag table must come from an audit of what each handler reads, not from the help prefixes (already known to be wrong for `--json`). Added a test tying the characterization corpus to the table, and a note to keep flag order so the three help-reading tests stay green.
- B5c corrected. The draft's uniform `--flag=value` changes argv pinned by `test_ui_jobs.py:146-156`, `178-195`, `205-217` and `308`, which the repo's TDD rule forbids editing without asking. The owner then chose the uniform form and approved those test edits, so the item moved to plan 42 E1. The draft also cited `test_fix_ui_security_jobs.py` as the home for the new tests; that file covers job runner limits, so the tests go in new files. Noted that the `_metric_args` fix is already on master.
- B8 corrected. The draft said a `normalize_ui(args)` step keeps `args.ui_args` for existing tests, but `test_ui_cache_cli.py:43` and `test_ui_backup_cli.py:24` read `ui_args` straight from `parse_user_commands`, and core offers no post-parse hook for plugins. The subparsers now write `ui_args` themselves (set_defaults plus a small Action), so handlers and tests are untouched. Also spelled out that the shared source flags need two registrations (real defaults on `ui`, SUPPRESS on verbs), since an explicit `default=` defeats `argument_default`. Dependency on B1 removed; it was not real.
- B1 extended with a bug found while measuring: `vmn-exp --debug run app -- true` fails with `usage: vmn ... invalid choice: 'run'` because `_to_vmn_argv` (main.py:17-21) passes any argv starting with `-` through unchanged. Added the fix and pure tests. Also added `skill`, `migrate`, `login` to the help epilog (they are intercepted before the parser and appear nowhere), and an `epilog` field on `Frontend` so core need not know them.
- B9 rebuilt on measurements the draft did not take (scratch clone outside the repo, remote pointed at a scratch bare repo). Results: no-op wrap 0.47 s; `python -c pass` 1.02 s; SDK script 0.43 s alone, 1.0 s wrapped; `start_run` spends 0.30 of 0.32 s in `checkout_source` with about 15 git subprocesses; env probe at most 0.05 s.
- B9c dropped and moved to refuted: the env probe is below the draft's own 100 ms threshold, and the change would have weakened the isolated `-I` capture.
- B9b raised P2 to P1 and made self-contained: the 0.5 s sleep is the largest measured removable cost. The loop is extracted into a new pure module with injected clock and wait, instead of the draft's B9a plan to add required `clock/sleep/popen/hostname` constructor parameters to `_Supervision`, which would break the three direct constructions in `test_exp_rerun_recording.py:140, 155, 165`. Its tests are now real unit tests with no process.
- B9a shrunk M to S: it now records the measured table and adds count-based git-process budget tests in the style of `tests/test_git_process_budget.py`. Dropped `PhaseTimer`/`run_phases.py` (the existing `measure_runtime_decorator` under `--debug` already produced the table) and the wall-clock serial test (flaky, and not the style of the cited budget test). Noted honestly that these are regression guards that pass on arrival, not red-green pairs.
- B9d changed from an open investigation (P3) to a concrete item (P2): the duplicate capture is now measured and located, with B9a's bound as the red test; the owner chose a re-measure after adoption and then trimming redundant git calls.
- B7 corrected: `ui backup` and `ui diag` usage errors already return 2 (`backup_cli.py:70`, `diag_cli.py:37`), so the draft's test `test_ui_backup_without_a_path_is_a_usage_error` would never have been red. Removed them, the vague finish-flags site, and the `exit_codes.py` constants module (existing code uses the literal 2; a module for three ints is an abstraction nobody asked for).
- B4c: added the behaviour change the draft understated. Because `defaultBaseline` prefers `base` (`runChangesBaseline.ts:36-40`), an untracked-only run that has a previous run will now open on its own file list instead of the previous-run diff. Also noted `test_ui_patch_presence.py` is a new file.
- B4a: confirmed the exact-dict tests (`test_exp_show_patch_views.py:11-17, 103-105`) stay green only if the new keys appear solely when a tarball exists; made that explicit in the approach and added a test for it. Moved the `show` test to its own new file rather than the draft's either-or.
- B2, B3, B4b, B6: evidence line numbers re-checked and corrected where they had drifted (e.g. show's Metrics block is experiment.py:879-884). B3 gained a note that apps with a declared primary metric are re-ordered by default, so their default listing changes too. B6 lost its conditional reference to B5b.
- Refuted list: kept the draft's five entries with re-verified evidence, corrected the exit-code entry (ui backup/diag already 2), and added three: the env-probe hypothesis, the unreproduced 5 s magnitude with the measured causes, and the stale premise that the two excluded fixes are still in flight.
- Suggested order changed to put B9b early (smallest diff, largest measured win).
