# 17 — Detached HEAD, branch inference, goto output and config-key migration

Status: **done 2026-10-10** (commits `fcfd49c7`, `b54d0e52`, `30d02779`, `94086722`, `d12fa2f8`, `0639e3c9`). Fixes four user-visible problems in core vmn.
CI is the main audience: many companies run `vmn goto` (and `vmn stamp`) in every CI job,
usually in a detached checkout, so every change below must keep today's CI flows working.

Paths are under `packages/vmn/src/version_stamp/` unless noted.

---

## 1. Problems

| # | Symptom | Cause |
|---|---|---|
| P1 | `[WARNING] Migrating top-level 'default_release_mode: optional' …` on every command, twice on `goto` | `compat/config_keys.py` migrates in memory on every conf load and nothing ever rewrites the file. `goto` builds `VersionControlStamper` twice (`cli/output.py:409`) |
| P2 | `vmn_tracking_remote__origin_<branch>__from_<sha5>` branches appear, a new one per detached commit (they pile up in persistent CI workspaces) | `GitBackend.__init__` → `get_active_branch` → `get_branch_from_changeset` (`backends/git_branch.py:57`) creates and possibly checks out that branch whenever HEAD is detached on a commit no local branch contains. Runs for **every** command except `show` (main repo and every dep `_update_repo` opens) |
| P3 | Stamping from a detached CI checkout **deletes the branch's own branch conf** and pushes the deletion; the branch conf is ignored; `whitelist_release_branches` refuses | Same cause: `active_branch` becomes the invented name, so `resolve_branch_conf_path` (`stamping/base.py:186`) misses `branch_conf/<branch>/`, `_collect_stale_branch_confs` (`stamping/publisher.py:493,805`) treats it as another branch's conf, and the whitelist check (`publisher.py:299`) compares the invented name. `stamped_on_branch` in the tag records the invented name |
| P4 | Ambiguous branch picked silently | Several branches contain HEAD → the first **alphabetically** wins (local first, then remote). A CI job for a just-cut `release/1.2` can resolve to `master`. The remote pick uses "contains HEAD", not "tip is HEAD", so a branch whose tip *is* HEAD can lose to an older one and stamp then fails as detached |
| P5 | `goto` prints `Updated ../dep to changeset <sha>` when nothing moved | `_update_repo` (`cli/output.py:562-593`) logs `Updating`/`Updated` unconditionally |

P3 reproduced on `0.10.2-rc.15`: fresh clone, `git checkout -f <sha>`, `git branch -D master`,
`vmn stamp -r patch app` → stamp commit on `origin/master` removes
`.vmn/app/branch_conf/master/conf.yml`.

### What the branch creation was for (keep it working)

Added in 0.8.0 (`895fea51`) so `vmn stamp` works in CI checkouts that are detached at the tip
of a remote branch (Jenkins `git checkout -f <sha>`, no local branch): the constructor puts
HEAD on a local branch tracking that remote branch, so stamp can commit and push. `vmn goto
<app>` without `-v` relies on it too: it checks out "the active branch". `release` (without
`--stamp`) and `add` do **not** need it: they already push only their tag
(`backend.tag(..., push=True)`), and work from any detached commit (verified); their only
side effect is the invented branch the constructor leaves behind.

---

## 2. Principles

1. **Opening a repo never changes it.** No command creates branches or moves HEAD as a side
   effect of building a backend (main repo or deps). Today's `read_only=True` behaviour
   becomes the only behaviour of the constructor.
2. **Only two places put HEAD on a branch:** commands that create a commit (`stamp`,
   `release --stamp`, `init`, `init-app`) and `goto` without `-v` (main repo + unpinned
   deps). `release` without `--stamp` and `add` push only their tag and stay detached. Each calls one
   explicit `ensure_on_branch()`.
3. **Real branch names only.** vmn checks out `<branch>` (creating a local branch tracking
   `<remote>/<branch>` when missing, as `git checkout <branch>` does). It invents a name only
   in the one compatibility fallback of §4 (diverged local branch).
4. **One resolver, no silent guessing.** The same function picks the branch everywhere;
   when several branches remain it keeps today's alphabetical pick but warns, listing the
   candidates and the fix.
4a. **Branch identity.** Wherever vmn uses the branch name as an identity — branch conf
   lookup, stale branch-conf removal, `whitelist_release_branches`, `stamped_on_branch` — a
   `vmn_tracking_remote__*` branch counts as its upstream's name. Fixes P3 for checkouts that
   already sit on such a branch (and for the §4 fallback).
5. **CI compatibility.** Every flow that ends on a branch today still ends on a branch at the
   same commit. Only the branch name changes (to the real one).

---

## 3. Branch resolver (`backends/git_branch.py`)

`resolve_branch(hexsha, require_tip, use_ci_hint)` returns a branch name or raises
`AmbiguousBranch(candidates)` / `NoBranch`. Pure lookup, no side effects. Candidates are
local branches and selected-remote branches (prefix stripped, deduped). With
`require_tip=True` a candidate qualifies only if `<remote>/<b>` (or the local `b` when it has
no remote) points exactly at `hexsha`; otherwise it qualifies if it contains `hexsha`.

First rule that yields exactly one qualifying branch wins:

1. **CI hint** (main repo only, `use_ci_hint=True`): the branch named by the CI system, if it
   qualifies. Read from `GITHUB_HEAD_REF` / `GITHUB_REF_NAME` (when `GITHUB_REF_TYPE=branch`),
   `CI_MERGE_REQUEST_SOURCE_BRANCH_NAME` / `CI_COMMIT_REF_NAME`, `BRANCH_NAME`, `GIT_BRANCH`
   (strip `<remote>/`), `BUILDKITE_BRANCH`, `CIRCLE_BRANCH`, `BITBUCKET_BRANCH`. Never applied
   to deps (the env names the main repo's branch). A hint that does not qualify is ignored with
   a debug line.
2. **The branch you were last on**: walk the HEAD reflog (`checkout: moving from A to B`)
   newest to oldest; the first `A` that is an existing local branch (git's `@{-N}`). Covers
   `goto -v` hops (`master → 1.0.90 → 1.0.95 → back` = `master`).
3. **Tip match**: the branches whose tip is `hexsha`. Unique → it.
4. **Stamping branch**: only when `hexsha` itself carries a version tag of the app, that tag's
   `stamped_on_remote_branch` (never an ancestor's: a feature branch's ancestor was stamped
   on `master`).
5. **Unique container**: exactly one qualifying branch.
6. **Legacy alphabetical pick** (compatibility, decided 2026-10-10): ≥ 2 qualifying branches
   → today's choice (first local branch alphabetically, else first selected-remote branch),
   with a warning listing the candidates and the fixes (set the CI branch variable, or
   `git checkout <branch>` first). 0 → `NoBranch`.

`active_branch` for a detached HEAD becomes the resolver's answer (plain name) or `None`,
and `remote_active_branch` its `<remote>/<b>`; `detached_head` stays true. This is what
`show` reports today, now for every command.

---

## 4. `ensure_on_branch()` (`backends/git_branch.py`)

Called only from the places in §2.2. No-op when HEAD is already on a branch.

| Caller | Resolver call | Then |
|---|---|---|
| `stamp`, `release --stamp`, `init`, `init-app` (in `cli/entry.py` right after `VMNContainer` is built, i.e. the same moment the constructor did it before) | `require_tip=True`, `use_ci_hint=True` | local `b` missing → `git checkout -b b --track <remote>/b`. Local `b` at `hexsha` → `git checkout b`. Local `b` an ancestor of `hexsha` and not checked out in another worktree → fast-forward it, then check out. Local `b` diverged → today's behaviour with a warning: `vmn_tracking_remote__<remote>_<b>__from_<sha5>` at `<remote>/b`, checked out (§7 Q3) |
| `goto` without `-v`, main repo (`cli/output.py:386`, replaces `checkout_branch()`) | `require_tip=False`, `use_ci_hint=True` | `git checkout b` (git creates the tracking branch if needed); `--pull` then pulls as today |
| `goto` without `-v`, dep with no `branch`/`tag`/`hash` pin (`_update_repo`) | `require_tip=False`, `use_ci_hint=False` | same |

Resolver failures (`NoBranch` only; ambiguity resolves via the warned legacy pick):
- commit commands: `NoBranch` leaves HEAD detached; stamp then fails with
  its existing "detached" error, extended with the candidate list and the fix
  (`git checkout -B <branch> <remote>/<branch>` before `vmn stamp`). Same exit code as today.
- `goto`: error listing candidates and `git checkout <branch>`; exit 1.

Also audit `version_stamp.api` callers that commit (the vmn-exp SDK cold start, auto-init in
stamp): they must go through `ensure_on_branch()` too.

### Existing `vmn_tracking_remote__*` branches

`ensure_on_branch()` deletes local `vmn_tracking_remote__*` branches that are not checked
out in any worktree and have no commits beyond their upstream (zero data loss; the namespace
is vmn's own). One debug line per deletion. The branch currently checked out is left alone
until the user moves off it. (§7 Q2)

---

## 5. Config-key migration (P1, `compat/config_keys.py`, `stamping/publisher.py`)

- Read paths (every command): migrate in memory as today, log at **debug**, not warning.
- `vmn stamp` (and `release --stamp`): before writing stamp files, rewrite the loaded conf
  file (`self.app_conf_path`, after `_migrate_branch_confs` remaps it) so the deprecated keys
  are gone; the file is already in `version_files`, so it lands in the stamp commit and is
  covered by `_revert`. Text-level edit that keeps comments and order:
  - top-level `default_release_mode: optional|strict` → `release_mode_policy: <v>` (line
    dropped if `release_mode_policy` already exists);
  - `conventional_commits: {default_release_mode: …}` → same, and `conventional_commits: true`
    when the mapping becomes empty.
  One info line: `Migrated deprecated keys in <path>`. `--dry-run` prints `Would migrate …`.
- `vmn_version_file` backend warning stays (needs a user decision); `create_verinfo_files`
  is already debug.

---

## 6. goto output (P5, `cli/output.py:_update_repo`)

- Drop `Updating <path>` to debug.
- Compare the commit before and after: unchanged → `<path> is already at <ref> (<sha8>)`;
  changed → `Updated <path> to <ref> (<old8> -> <new8>)`, where `<ref>` is `branch X` /
  `tag T` / `changeset <sha8>`. Keep the `Updated <path> to` prefix for anyone grepping logs.

---

## 7. Open questions (defaults in bold)

1. Ambiguous after all rules: **decided** — legacy alphabetical pick + warning (§3 rule 6),
   so existing setups keep working.
2. Auto-delete stale `vmn_tracking_remote__*` branches (§4): **yes** vs only document
   `git branch --list 'vmn_tracking_remote__*' | xargs git branch -D`.
3. Stamp with a diverged local `<branch>`: **decided** — fall back to the old invented
   name with a warning; §2.4a keeps branch confs/whitelist correct there.
4. ~~Tags-only push for `release`/`add`~~: in scope (decided 2026-10-10). They already push
   tags only; this change keeps them off the `ensure_on_branch()` list and locks it in with
   tests. `release --stamp` stays on the list.

---

## 8. Tests (write first; core suite, `tests/`)

New `tests/test_detached_ci.py`, CI-style fixture: fresh clone, `git checkout -f <sha>`,
local default branch deleted.

- `goto -v`, `gen`, `config gen`, `snapshot list`, a dep `_update_repo`: `git branch` and
  HEAD unchanged (extend `tests/test_backend_side_effects.py`).
- `release -v <rc>` and `add` from a detached commit that no branch has at its tip: succeed,
  push only the new tag (`git ls-remote`), HEAD stays detached, no new local branch.
  `release --stamp` from the CI fixture at a remote tip ends on the real branch.
- stamp at a remote tip: ends on local `master` tracking `origin/master`, no
  `vmn_tracking_remote__*`, tag `stamped_on_branch: master`.
- stamp keeps `branch_conf/master/conf.yml` and applies its template (P3 regression).
- `whitelist_release_branches: [master]` stamp from the CI fixture succeeds.
- two remote tips at HEAD: `BRANCH_NAME=release/1.2` picks it; no hint → alphabetical pick
  plus a warning listing both.
- HEAD contained in `master` but tip of `feature` → stamp uses `feature`.
- `goto -v` then `goto` returns to the reflog branch (`feature/x`, not alphabetical
  `aws/prod`); two hops; fresh clone falls through to tip match.
- dep without pin: `goto` back resolves without CI hint.
- local `master` behind `origin/master`: stamp fast-forwards it; diverged: legacy branch +
  warning, branch conf kept.
- already on a `vmn_tracking_remote__origin_master__*` branch: stamp keeps and applies
  `branch_conf/master/conf.yml`, whitelist `[master]` passes, `stamped_on_branch: master`.
- stale `vmn_tracking_remote__*` (merged) deleted; one with extra commits kept.
- `tests/test_git_backend_branches.py::test_detached_head_picks_branch_of_selected_remote`
  asserts the invented name; it encodes the old behaviour. **Stop and ask before changing it**
  (TDD rule); proposed replacement asserts `active_branch == "feature"` and no new branch.
- Config: read commands print no warning (`capfd`), stamp rewrites the file with comments
  kept, `--dry-run` leaves it, revert on failed push restores it, nested form.
- goto output: second `goto` prints `already at`, a moved dep prints `old -> new`.

---

## 9. Work split (worktrees, each red → green)

| Worktree | Scope | Files | Depends on |
|---|---|---|---|
| A | §5 config-key migration | `compat/config_keys.py`, `stamping/publisher.py`, `tests/test_config_key_migration.py` | — |
| B | §6 goto messages | `cli/output.py` (`_update_repo` only), `tests/test_goto.py` | — |
| C1 | §3 resolver + side-effect-free constructor | `backends/git_branch.py`, `backends/git.py`, `tests/test_branch_resolver.py` | — |
| C2 | §4 `ensure_on_branch` wiring, stale-branch cleanup, P3 tests | `cli/entry.py`, `cli/output.py` (`goto_version`, `_update_repo` call), `tests/test_detached_ci.py` | C1, B (same file) |

Docs after C2: README `goto`/CI `<details>` (detached CI checkouts, CI env hint, migration
note for the old branch names), CLAUDE.md `vmn goto` line, `docs/agent-skill.md` only if
`cli/skill.py` changes.

---

## 10. Follow-ups (left out of the first pass, 2026-10-11)

Each item is independent; TDD as usual. Paths under `packages/vmn/src/version_stamp/`.

| # | Item | Why it was left out | Plan | Needs approval |
|---|---|---|---|---|
| F1 | ~~**Run the old-vmn compat tests**~~ (skipped by decision 2026-10-11) (`tests/compat/test_version_compat.py::test_backward_compatability_with_0_3_9_vmn`, `::test_problem_found_in_real_customer`, `tests/test_release.py::test_backward_compatability_with_0_8_4_vmn`) | They skip without Docker (`tests/vmn_fixtures.py:319`), so nothing in this plan was checked against old vmn | Run on a Docker host first (`./tests/run_pytest.sh --specific_test backward_compatability` and `real_customer`). Add one test: a conf rewritten by the new stamp (`release_mode_policy`, no `vmn_version_file`, `conf: {}`) is read by the previous released vmn (0.10.x image) without error — CI fleets run mixed vmn versions | — |
| F2 | **`active_branch` carries the identity**; a separate `local_branch` field holds the git ref | Broad: `active_branch` is read for git refs in push (`backends/git_ops.py` refspec), `checkout_branch`, the outgoing range (`git_branch.py`), `prepare_for_remote_operation`, `git_tags.py`, worktree code | Resolve identity once (constructor and end of `ensure_on_branch`), store it in `active_branch`; add `local_branch` for the ref users above; delete `logical_branch()` and its 8 call sites. Grep every `active_branch` reader (core + vmn-exp) and classify ref vs identity first | — |
| F3 | **Lazy branch resolution** (`active_branch`/`remote_active_branch` as cached properties) | Saves 1–2 git processes per detached dep per command (`for-each-ref --contains`, reflog); the `--contains` cost pre-dates this change | Properties resolved on first read; `repo_status` / `dep_backend` only call `in_detached_head()` for deps. Measure with `GIT_TRACE2_PERF` per plan 15 §1 before/after | — |
| F4 | **Reuse the constructor's containment lookup in `ensure_on_branch`** | A per-backend cache broke `test_require_tip_only_accepts_branches_whose_tip_is_head` (it moves refs between two calls) | Cache keyed by a ref generation counter bumped by every ref-changing backend op (`checkout`, `branch`, `_fetch`, `pull`, `push`, `tag`); external ref changes between calls are the test's case — keep the cache per command only | — |
| F5 | **Remove dead `read_only`** from `GitBackend`/`get_client`/stamper/`dep_backend` | `tests/test_backend_side_effects.py:74` passes `read_only=True`; vmn-exp `snapshot/stores.py:62` reads `params["read_only"]` (a params key, unrelated to the backend) | Drop the backend kwarg; keep the params key for vmn-exp (or rename it `lock_free`); change that one test call | Yes (test edit) |
| F6 | **One "needs a branch" entry point** | CLI passes `ensure_branch` into `IVersionsStamper.__init__`; vmn-exp cold start calls the backend directly and never re-resolves conf paths; the command list is a hard-coded table plugins can't extend | Stamper method `vcs.ensure_on_branch()` = backend call + re-run `initialize_paths` and the conf load when the branch changed; commands declare "commits" in their spec like `read_only_actions` (`cli/plugin_api.py`); cold start uses the method | — |
| F7 | **Robust conf loader** (`data.get("conf") or {}`) in every conf reader (`stamping/base.py:159,178`, `cli/config_tui.py`, `cli/worktree_freeze.py`, `compat/branch_conf.py`) | The writer's `conf: {}` guard covers vmn's own rewrite; a hand-written bare `conf:` still crashes | Fix the readers; keep the writer guard (older vmn versions read the same committed files) | — |
| F8 | **Rename `_write_version_to_vmn_version_file`** (e.g. `_write_last_known_version_file`) | Latent trap: the `_write_version_to_<backend>` dispatch would call it with the wrong arguments if a `vmn_version_file` backend ever reached the loop again | Rename + one test that a `vmn_version_file` entry injected after load is ignored | — |
| F9 | **Test-only re-exports**: `rewrite_deprecated_conf_keys` from `compat/config_keys.py` (`noqa: F401`), `LEGACY_TRACKING_PREFIX` from `backends/branch_resolver.py` | Tests import from those paths | Point the test imports at `compat/conf_rewrite.py` / `core/constants.py`, drop the re-exports | Yes (test edit) |
| F10 | **`checkout_branch` returns bool** instead of an unused hexsha | Existing API, outside the change | Return `True/False`; callers already only test `is None` | — |
| F11 | **Git-process budget test** | No guard against the detached paths regressing | One test counting `git` executions (as `tests/test_backend_side_effects.py` does) for: attached stamp = baseline, detached CI stamp ≤ baseline + 2, detached goto ≤ baseline + 2 | — |

Order: F8/F7 (small), F2+F3+F4 together (same accessors), F6, the rest.
