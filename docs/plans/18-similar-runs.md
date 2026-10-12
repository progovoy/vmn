# Plan 18: "Has anyone run something like this before?" — similar runs

> A researcher about to run (or looking at) an experiment wants to know which past runs
> — by anyone, in this app or others — were similar, who ran them, when, and how they
> did. Nobody should have to tag runs by hand for this to work.
> Paths are relative to `packages/vmn-exp-sdk/src/vmn_exp/` unless they start with
> `packages/`, `tests/` or `docs/`; `cli/`, `gitmode/`, `importers/` and `ui/` are under
> `packages/vmn-exp/src/vmn_exp/`.

Status: **implemented** (2026-10). This document describes what was built; the user
docs are [experiments.md `similar`](../vmn-exp/experiments.md#similar),
[Intent](../vmn-exp/experiments.md#intent-what-a-run-is-for),
[sdk.md](../vmn-exp/sdk.md#similar-runs), [ui.md](../vmn-exp/ui.md#similar-runs) and
[migrating-from-mlflow.md](../vmn-exp/migrating-from-mlflow.md#similar-runs-for-imported-runs).
§7 lists what was decided differently from the proposal, §8 the known limits.

## 1. Decisions

- **Facts on the record, derived data off it.** Things that are true about a run and
  cheap to keep — who ran it, which files/functions the diff touched, the commit
  subjects — are written into the record, because they are only reliably known at
  submission (branches get deleted, containers run git-free, shallow clones lose history)
  and the record is what travels (`push`, buckets, the server). So is an *intent*
  written by a human or their AI (§4): it is authored text, not something we can
  recompute. Similarity *scores* are never written into records, because they change
  whenever any run is added or the weights change. They are computed from the
  rebuildable index, following the architecture rule in [README](README.md) ("storage
  is the source of truth; everything else is rebuildable").
- **Features are a `features` log entry, not a `metadata.yml` key.** `metadata.yml` is
  written once by the `create_exclusive` claim and `push` merges only `archived`/`note`, so
  old records cannot be given new metadata safely. Log entries are append-only per writer,
  already synced/pushed, and are how tags and rewinds already add to old runs. New runs
  write the entry next to their `create` entry; backfills append it under the host's
  writer id. The fold keeps the entry with the highest `features_version`, and the latest
  of those.
- **The branch is already on the record.** `metadata.branch` (`logical_branch()`) is
  written for every git-mode run and copied by git-free runs and reruns; it is a row and
  query field. Capture does not repeat it in `features`; only an MLflow refresh puts one
  there (§3.6).
- **vmn never needs an AI model.** v1 = structured features + a weighted score + the
  reason each run matched. v2 = the user's own AI (any agent, any model) reads the diff and
  writes an *intent* (`--intent-file` / `--context-file`); vmn stores it on the record and
  matches it lexically, and the agent re-ranks the candidates it gets back. A skill
  teaches agents this loop. No embedder, vectors or network calls inside vmn.
- **Ask before submitting.** `vmn-exp similar <app>` with no ref uses the current
  working tree's features, so you can check before creating a run.

## 2. What "similar" is made of

| Signal | Source | Similarity | Default weight |
|---|---|---|---|
| Author | `features.author` (§3.1) | shown, not scored (row field `author`, filter with `--query`) | — |
| `code` | `code_verstr` (base version + commit), else `base_version`, else `imported_from.source_commit` | same commit 1.0; same base version 0.7; version distance decays (git-free proxy for ancestry) | 2 |
| `files` | `features.changed.files` (+ `untracked`) | Jaccard | 2 |
| `symbols` | `features.changed.symbols`: `@@ … @@ <context>` hunk headers **and** definitions on added/removed lines, any language | Jaccard | 3 |
| `inputs` | `row["inputs"]` (uri/digest/kind), registry `<name>@<N>` | same digest 1.0; same dataset name, other version 0.6 | 2 |
| `params` | `row["params"]` | key Jaccard × mean value closeness (positive numbers: `1 - min(1, \|log10(a/b)\|/2)`; others: equality; non-finite/huge values never raise) | 1.5 |
| `entrypoint` | row/run-state `command`, else `features.entrypoint` | same script 0.7; + same subcommand/args 1.0; launchers (`torchrun`, `accelerate launch`, `deepspeed`, `mpirun`/`mpiexec`, `srun … --`, `horovodrun`, `python -m torch.distributed.run`, …) are looked past | 1 |
| `objective` | metric names minus `params` keys minus `sys_*` | Jaccard | 1 |
| `branch` | `row["branch"]`, else `features.branch` | equality | 0.5 |
| `text` | intent text + keywords ×3, name, note (else create note), tag keys and values, commit subjects, the create entry's `hypothesis` | BM25, normalised per query by the best candidate | 1.5; code + inputs when the target has an intent or a context |

Defaults live in `core/similar_score.py` (`DEFAULT_WEIGHTS`, `resolve_weights`); conf
`experiment.similar.weights.<signal>` overrides them (valid numbers ≥ 0 only; anything
else is ignored). A signal missing on either side is left out of the score
(renormalised), not counted as 0, so imported MLflow runs (no code) are still comparable
on params/inputs/objective. A features entry naming no changes is a clean tree, not
missing data: two clean trees score 1.0 on `files`/`symbols`, a clean tree against changed
code 0 (unknown: no features entry, `source: mlflow`, an export's author-only version-0
entry, a `backfill` entry on a dirty code verstr, i.e. a partial one). `files`/`symbols`
get half weight when either side's changes are a branch's cumulative diff
(`changed_source: commit`, §3.6). Reasons are the top 3
contributions, candidate first (`same dataset imagenet@3`, `2 shared functions:
loss.py::focal_loss, …`, `lr 3e-4 vs 1e-4`, `shared: focal loss, class imbalance`).

## 3. v1 — structured similarity

### 3.1 Formats

```yaml
# features log entry
type: features
features_version: 1            # core/features.py FEATURES_VERSION
source: capture | rerun | export | backfill | mlflow
author: {writer: gpu-07, git_user_email: a@x.io, os_user: alice, source: git | export | env | commit | host | mlflow}
changed: {files: [...], symbols: ["path::name", ...], untracked: [...]}   # untracked: capture only
commits: ["subject", ...]
entrypoint: "train.py"          # MLflow only; vmn runs use their command
branch: "feat/x"                # MLflow refresh only
changed_source: commit          # MLflow --repo only
truncated: true                 # only when caps cut a list
```

- Empty values are omitted (`build_features_entry`). Caps: 200 files, 500 symbols,
  50 commits, 200 untracked paths.
- `core/features.py` (pure): `features_from_patches(patch_texts)` over unified diffs and
  `git format-patch` mboxes (`core/features_patch.py`: `From:` with RFC 2047, folded
  `Subject:` with one `[PATCH n/m]` stripped, cover letters skipped, `diff --git` paths
  incl. quoted/renamed/copied/deleted/binary, a diff pasted into a commit message
  forgotten at the message's `---` separator; `core/features_symbols.py`: `hunk_symbol`,
  `defined_symbol` — linear-time, lines over 500 characters define nothing). Items may be
  `(prefix, text)` pairs, so dep files sit under the dep's configured path.
- `author` comes from `core/identity.py` (`actor_identity`, moved out of `registry/log.py`,
  which re-exports it): `run_author(cwd, fallbacks)` fills `writer`/`os_user` and takes
  `git_user_email` from git config (`source: git`, 2 s timeout), else the caller's
  fallbacks in order, else `source: host` with no email.
- Row field `author` (`fold.author_display`): `git_user_email`, else `os_user`, else
  `writer` (blank values count as missing), else null.

### 3.2 Writing them at submission

- Git mode: `gitmode/checkout.py:record_run` is the single hook (CLI create/run/sweep,
  SDK). `gitmode/features.py:capture_features` builds the entry from the capture's
  in-memory patch texts (the code object is never loaded) plus the capture's own
  untracked listing (`SnapshotCapture.untracked_paths`), and `writer.create_run(...,
  features=)` writes it in the same batch as the `create` entry. Email fallbacks:
  `VMN_EXP_AUTHOR` (`env`), then the first local commit's `From:` (`commit`).
- Git-free (`core/from_snapshot.py` via `core/snapshot_features.py`): an exported tree
  carries no patches, so the facts are copied from the exported run's own features, which
  `vmn-exp export` writes with `exported_by` to the sibling `vmn_features.yml` (`source:
  export`, keeping its version; read before the SDK takes the `VMN_EXPERIMENT_DIR` lock;
  the exported run's log in `vmn_experiment.yml` is read only for an older export without
  it, up to 1 MiB). Email: git
  config in the tree, else `exported_by` (which `vmn-exp export` now writes), else
  `VMN_EXP_AUTHOR`. Without a source entry only the author is known and the entry is
  written at `features_version: 0`, so the backfill still selects it.
- Rerun (`cli/rerun.py`): copies the original's facts when they are at the current
  version, else derives them from its patches; the author is the rerunner alone (git
  config, then `VMN_EXP_AUTHOR`, else `host`), `source: rerun`. Forks capture their own
  features and inherit neither features nor intent.
- `vmn snapshot` records are not runs; out of scope.
- Best-effort like `env`: a failure logs a warning and the run is created without the entry.
- `vmn-exp show` treats `features` as a fact, not an event (`cli/views.py:FACT_ENTRY_TYPES`):
  not in the text log or `log`/`log_total`; `show --json` has it as `features`. The UI
  run log keeps it (paging offsets) and describes it in one line.

### 3.3 Index

- `core/fold.py` / `core/fold_facts.py`: `features` (highest int `features_version`,
  then latest), `intent` (latest; a blank text clears it), `hypothesis` (the first create
  entry's, like `create_note`); accessors `fold_features`, `fold_intent`,
  `fold_hypothesis`. None is pre-created in `new_fold`; malformed entries fold into nothing.
- They are **not** row keys (indexed lean rows must equal direct rows): side tables
  `IndexSnapshot.features_of/intent_of/hypothesis_of(verstr)` filled by
  `index_views.lean_row` and the direct-snapshot path. `fold_row` adds only `author` and
  `has_intent` (a bool on every row), which join `core/query.py` ROW_FIELDS and the webui
  `querySuggest.ts` list. One `SCHEMA_VERSION` bump: `exp-index-12`.
- `core/similar_profile.py` reads each run's signals once; `core/similar_index.py` is an
  inverted index `token -> verstrs` over `w:`, `file:`, `sym:`, `input:<digest>`,
  `ds:<name>`, `pkey:`, `cmd:`, `metric:` and `commit:<sha7>` tokens. Candidates = runs
  sharing ≥ 1 token, rarest token first, cap 5000. Built once per snapshot object
  (lock-guarded `WeakKeyDictionary`): ~0.8 s to build and ~0.25 s a query at 20k runs.
- `core/similar_score.py` (pure): `score(target, candidate, weights=None, text_score=None)
  -> (float, reasons, signals)`.
- `core/similar.py`: `similar_runs(snapshot, target, *, top=10, rows_filter=None,
  schema=None, weights=None, app=None)` and `similar_runs_multi(scopes, target, ...)`
  over `[(app, snapshot, schema)]`; `target_from_snapshot(snapshot, verstr, text=None,
  text_only=False, *, app=None)`. The target is `{"row", "features", "intent",
  "hypothesis", "text", "text_only", "command"?, "create_note"?, "app"?}`.
  - Excluded: the target, its `code_verstr`, and its whole run tree (outer run, every
    trial and the SDK runs they open, its own inner runs) — in the target's app only. A
    working-tree target excludes nothing.
  - Grouped by **run tree root** (`SimilarIndex.root`: a run with a parent or children;
    a missing ancestor still roots its subtree; cycles end the walk), else by
    `code_verstr`. Each group shows its member best on the group's goal metric
    (`goal_metric`: the schema-goal objective most of its rows carry), else the most
    similar; a container run only when alone; `group_size` counts them. Items sort by
    score, then newest, then verstr. Result items carry `goal: {metric, goal, value}`.
- `core/similar_search.py` (pure SDK) is what the CLI, the hint and the SDK share:
  `search`, `item_payload`, `find`, `conf_weights`, `hint_enabled`.

### 3.4 Surfaces

- CLI `vmn-exp similar <app> [-v <ref> | --latest] [--top 10] [--all-apps] [--query
  <expr>] [--archived] [--context <text> | --context-file <path|->] [--text-only]
  [--json]` (`cli/similar.py`, `cli/similar_args.py`, `cli/similar_output.py`).
  Read-only (`READ_ONLY_ACTIONS`). No ref = the current working tree (captured without
  creating a run, `features_for_working_tree`): the one action whose missing ref means
  the working tree (`show`/`restore`/`export` take the latest run), because it is
  mostly asked before submitting; the help says so. In git-free mode it needs `-v`,
  `--latest` or `--text-only`. Output: `<verstr>  <score>  <author|->  <age>  <status>
  <goal>=<v>|—  — <reasons>  (+N runs)` (`<app>/` under `--all-apps`); `--json` items
  `{app, verstr, name, score, reasons, signals, group_size, author, timestamp, status,
  goal, note, intent (first 2 KB), features}`.
- Submission hint (`cli/similar_hint.py`): `create` (before printing the verstr) and
  `run` (before the child), both after the lock is released, print up to 3 on stderr: `2
  similar runs: best val_loss=0.31 — <verstr> by alice@x.io, 3w ago (<reasons>)` (or
  `closest — …`). Its candidates come only from this host's persisted index
  (`ExperimentIndex.follower`, never a refresh from the store, whose reads the process
  exit would wait for); the new run is read from its own record. Skipped when that
  cache is cold, when it holds more than `MAX_INDEXED_RUNS` (4000) runs (counted, not
  loaded), for inner runs (`--parent`, `VMN_EXPERIMENT_ID`, `VMN_SWEEP_TRIAL`, a parent
  on the record), with `--no-similar` / conf `experiment.similar.hint: false`. 300 ms
  budget (`BUDGET_SEC`) on the calling thread: the search takes it as a deadline that
  the index build and the scoring check every 32 rows or candidates
  (`DEADLINE_CHECK_EVERY`), raising `SimilarDeadlineExceeded`; the steps it cannot
  interrupt (reading the new run, loading the persisted index) are checked between,
  and the index-size guard above keeps that load within the budget. Past it nothing is
  printed. Errors are debug-logged only. The SDK prints no hint.
- SDK `vmn_exp.sdk.reader.similar_runs(app_name=None, ref="latest", *, storage=None,
  top=10, query=None, context=None, text_only=False, all_apps=False)` (the reader
  convention; no working-tree target), `Run.similar(top=10)` (flushes its log first),
  `NoOpRun.similar() -> []`.
- UI (`ui/routes_similar.py`): `GET .../workspaces/{ws}/apps/{app}/experiments/{verstr}/similar?top=&all_apps=&archived=`,
  `GET .../workspaces/{ws}/apps/{app}/similar?text=&top=&all_apps=&archived=` and
  `GET /api/v1/similar?text=&top=&archived=` (next to `/api/v1/search`, over every
  viewable workspace via `routes_search.viewable`). `all_apps` on the per-workspace
  routes means that workspace's apps; scopes are keyed `(workspace, app)`. Scored from
  index snapshots (never the Postgres search rows), under the conf weights; `{items,
  truncated}`, ETag/304, viewer role; `top` 1..100, text ≤ 4 KB. Web UI: a "similar
  runs" card on run detail (this app / all apps, reasons as chips, intent collapsed)
  and a "similar" toggle on the leaderboard search box.

### 3.5 Re-deriving features

`vmn-exp similar-backfill <app> [--all-apps] [--dry-run] [--store …]`
(`cli/similar_backfill.py`, `core/code_patches.py`): a separate writing action, so
`similar` stays purely read-only. Registered in the git-free dispatch
(`_exp_run_without_repo`), takes the repo lock like `tag`.

It selects every run without a `features` entry at (or above) the **current**
`features_version`, which covers runs whose capture failed, runs captured by an older
version (or git-free author-only entries at version 0), and runs recorded before this
plan shipped. Running/stuck runs and imports (`imported_from`) are skipped.

- Load **only the patches** of the run's code object through `load_file` (never the
  untracked tarball; deps skipped when the marker says there are none), call
  `features_from_patches`, and append a `features` entry (`source: backfill`) under this
  host's writer id (`get_writer_id()`), which phase P0 made safe (§3.7).
- When the run already has an older entry, only the patch-derived fields (`changed`,
  `commits`, `truncated`, `changed_source`) are recomputed; `author`, `branch`,
  `entrypoint` and `changed.untracked` are carried over. Without one, the author is the
  first local commit's `From:` (`source: commit`) plus `writer` = the writer whose log
  holds the run's first `create` entry (a v1-migrated run: its run state's `host`). The
  base commit's author is **not** used (it is usually the upstream tip's author).
- Each code object is read and parsed once; a `from_snapshot` run's code object is found
  by code verstr (`find_code_key`, memoized). A clean tree gets a complete entry with
  nothing changed. A code object whose marker is missing → `partial` (no `changed`, or
  the older entry's). Code the store lists but cannot read → `failed`, nothing written,
  retried next time; any other per-run error fails only that run.
- Output: `<verstr>  backfilled|partial|skipped|failed[ (detail)]`, `<app>:` headers
  under `--all-apps`, then `backfilled N, partial P, skipped S, failed F` (` (dry run:
  nothing written)`); exit 1 if any failed. Idempotent.

Descriptions are a different path: a run submitted without a comment still gets its
features at submission, and its intent is added later with `vmn-exp add --intent-file` (§4).

### 3.6 MLflow imports

The importer already mapped params, metrics, user tags and datasets. `importers/mlflow_features.py`
now maps the `mlflow.*` tags similar runs uses (values stripped, blank = absent;
`mlflow.*` tags still never become vmn tags):

| MLflow tag | Goes to |
|---|---|
| `mlflow.user` | `features.author`: an email (contains `@`) as `git_user_email`, else `os_user`; `source: mlflow`, no `writer` |
| `mlflow.note.content` | metadata `note` (new imports; refresh sets it only when the record's note is empty — `push` already merges `note`) |
| `mlflow.source.git.branch` | metadata `branch` (new imports) / `features.branch` (refresh, when the record has none) |
| `mlflow.project.entryPoint`, else `mlflow.source.name` | `features.entrypoint` |
| `mlflow.source.name`, `mlflow.source.git.repoURL` | `imported_from.source_name` / `imported_from.repo_url` |

- New and resumed imports write a `features` entry (`source: mlflow`) under the
  `mlflow-import` writer.
- `--refresh-features` replaces the early `skipped` return for runs this importer wrote:
  a run without a features entry at the current version (or lacking the changes `--repo`
  now supplies) gets one, appended under `get_writer_id()` and flushed; outcome
  `refreshed`. The summary gains `refreshed R` only with the flag. The import writes
  through `resolve_experiment_storage` (writer mode, no lock) although it is listed in
  `READ_ONLY_ACTIONS`.
- `--repo <path>`: when `imported_from.source_commit` exists there
  (`version_stamp.api._commit_exists`), `changed` = files and symbols of `git diff
  $(git merge-base <default> <commit>) <commit>` via `features_from_patches`, with
  `changed_source: commit` (half weight). Default branch: origin/HEAD's target (if it
  resolves), else `main`, `master`, `origin/main`, `origin/master`. No textconv/external
  diff, at most 5 MB read (`truncated`), each commit diffed once across workers.
- The tracking-server client now imports dataset inputs (`run.inputs.dataset_inputs`;
  previously hard-coded `[]`), identical to `--mlruns`, which reads MLflow's FileStore
  layout: each `<run>/inputs/<id>/meta.yaml` with `source_type: DATASET` names a
  `<exp>/datasets/<source_id>/meta.yaml` (model inputs skipped; the experiment's
  `tags`/`datasets`/`traces`/`models` folders are not runs).

### 3.7 Prerequisite: appending to another host's log (P0)

Appending under `get_writer_id()` to a run on a `CachedSnapshotStorage` whose remote
already held a longer log for that writer took `CachedLogs._ship_new_lines`' start-over
branch and overwrote the remote log (a fresh clone, a cleared cache, a CI fleet sharing
one writer id). `storage/cached_logs.py` + `storage/cached_log_merge.py` now seed the
local log from the remote before the first append per (app, verstr, writer) and replace
the start-over branch with the same merge (with a newline-alignment guard and a
`LocalLogLock` that only the SIGTERM finalizer may give up on after
`LOCAL_LOCK_WAIT_SEC`). This made `add`/`tag`/`rewind`/intent/backfill/refresh appends
safe; `S3Logs.delete_log_segments` was removed.

## 4. v2 — bring your own AI: intent text from the user's agent

vmn ships no model and calls none. The semantic work (reading a diff and writing down
what an experiment is *for*) is done by whatever AI the user already runs — Claude Code,
Cursor, a CI script calling any API — through plain CLI calls. vmn stores the result as a
fact on the record and matches it deterministically. A skill teaches agents the loop.

### 4.1 The `intent` entry

```yaml
# log entry; latest wins (fold side table intent_of)
type: intent
text: |                       # markdown, stripped, capped at 16384 UTF-8 bytes
  Hypothesis: focal loss (gamma=2) fixes the minority-class recall drop seen in t4.
  Changed: src/loss.py::focal_loss (new), src/train.py::train_step uses it.
  Data: imagenet-lt@3. Expect: val_recall_min up, val_loss roughly flat.
keywords: [focal loss, class imbalance, long tail, reweighting, gamma]   # <= 50
generator: claude-opus-5-5    # optional; absent = written by a human
source: user
truncated: true               # only when the text was cut
```

Built by `core/intent.py:build_intent_entry(text, keywords=None, generator=None)`
(keywords: list/tuple or a comma string, stripped, deduped case-insensitively; numbers
and dates become text; an empty text or other types raise `ValueError`) and
`parse_intent_file` (YAML front matter between `---` and `---`/`...`; an unclosed block
is text). Written through:
- `vmn-exp create|run <app> --intent "<text>" | --intent-file <path|->`
  (`cli/intent_arg.py`, `-` = stdin, read once). The input is checked before anything is
  written, a cold start's baseline stamp included.
- `vmn-exp add <app> [-v <ref>] --intent-file <path|->`: add or replace an intent later
  (the latest run without `-v`, like `--note`); this is how old runs are backfilled.
- SDK `start_run(intent=…, intent_keywords=…)` (checked before anything is created),
  `run.set_intent(text, keywords=, generator=)` (also after `finish()`, synced at once);
  `NoOpRun.set_intent` is a no-op. Sweep trials and forks start without one.

The fold lets a blank text clear the intent, but no writer can produce one (the builder
refuses it); a new intent replaces the old. It is not the `note`: the note stays the
short one-liner `list` shows, while the intent is the long description used for
matching. `-f`'s `hypothesis:` (create entry) also feeds the text signal.

### 4.2 Matching text without a model

- `core/similar_text.py` (pure): a tokenizer (lowercase; splits on punctuation, `_` and
  camelCase; stopwords and 1-character tokens dropped) and BM25 (saturating query-term
  weights) over each run's text document (§2), with `w:` tokens in the §3.3 inverted
  index. Changed symbols stay structured only, so nothing is counted twice. It is the
  single `text` signal; an intent or context on the target raises its default weight to
  code + inputs. Its reasons show the shared keywords (`shared: focal loss, class
  imbalance`).
- Lexical matching is enough because the agent expands synonyms twice: once in the
  keywords it writes onto each run, and once in the query it sends. Semantic judgement
  happens in the agent, which re-ranks the candidates it gets back (§4.3).

### 4.3 Querying with context

- `vmn-exp similar <app> --context "<text>" | --context-file <path|->`: a text query,
  combined with the target's features (the working tree without `-v`, the run with
  `-v`); it replaces that target's text document. A context file's front matter
  `keywords` join the query; other keys are ignored. `--text-only` drops the features
  (and needs no working tree), for questions like "has anyone tried label smoothing?".
- `--json` gives an agent everything it needs to re-rank and answer (§3.4).
- `vmn-exp show <app> -v <ref> --patch [--max-bytes N]` (`cli/views.py`): the show
  block, then the run's own text patches (`=== working_tree ===`, `=== local_commits
  ===`, `=== deps/<dep>/<type> ===`; never the untracked tarball), capped at 200000
  bytes on a UTF-8 boundary with a truncation line. Without a text patch: a one-line
  note on stderr, exit 0. `--json --patch` adds `"patch": {"text", "truncated"}` or
  `{"text": null, "reason": "no_code" | "code_missing" | "untracked_only"}` (the last
  with `untracked_files` when the tarball is readable).
- Backfill worklist: `vmn-exp list <app> --query "has_intent = false" [--last N] --json`
  — the existing list/query path, not a new flag.
- UI: the run-detail card shows the intent; free text is the "similar" mode of the
  leaderboard search box (per-app text route), and `/api/v1/similar?text=` serves the
  cross-workspace query.

### 4.4 The skill (`vmn-exp skill`, `cli/skill.py`)

A "Similar experiments" section (regenerated into `docs/vmn-exp/agent-skill.md`), so
any agent that installed the skill does this without being prompted:

1. **Before submitting a run:** read the change (`git diff HEAD`, unpushed `git log`)
   and write `intent.md`: hypothesis, which functions changed and why, key params,
   dataset, expected effect, front matter `keywords:` (synonyms, the problem's usual
   names) and `generator: <model id>`. Describe the change, not results. Never paste
   secrets or data; stay under ~2 KB.
2. `vmn-exp similar <app> --context-file intent.md --all-apps --json`; inspect the 1–3
   closest with `vmn-exp show <app> -v <ref> --patch --json`, tell the user who ran
   what, when, how it scored and how this run differs; re-rank on meaning.
3. Submit with `--intent-file intent.md` (CLI) or `start_run(intent=…)` (SDK).
4. **Backfilling when asked:** `vmn-exp list <app> --query "has_intent = false" --last N
   --json`, then `show --patch --json`, write an intent, `vmn-exp add <app> -v <ref>
   --intent-file -`. Runs missing automatic features: `vmn-exp similar-backfill <app>`.
5. **For questions** ("did anyone try X?"): `similar --context "<X plus synonyms>"
   --text-only --all-apps --json`, then answer citing verstrs.

### 4.5 Migration for v2

- Old vmn runs: their structured features come from the §3.5 backfill. Intents come from
  the skill's backfill loop (step 4), run by the user's agent at whatever scope and cost
  they choose. Runs without an intent still match on everything else.
- MLflow runs: their note (imported, or added by `--refresh-features`) already feeds the
  `text` signal. An agent can add an intent to them through the same loop (`show --patch`
  prints a no-code note for them).
- Privacy: vmn never sends anything anywhere. Whatever leaves the machine is the user's
  agent's choice, which keeps air-gapped use intact.

## 5. Phases (as built; TDD, parallel worktrees)

| Phase | Worktree | Content |
|---|---|---|
| P0 | `cached-log-seed` | seed/merge instead of start-over in `storage/cached_logs.py` (§3.7) |
| F | `features-fold` | fold of `features`/`intent`/`hypothesis`, side tables, `author`/`has_intent` rows + query fields, `exp-index-12` |
| X | `patch-features` | `core/features*.py` patch parsing, `core/identity.py` |
| S | `similar-core` | `core/similar*.py` (text, profile, score, index, similar) |
| V | `show-patch` | `show --patch [--max-bytes]` |
| C | `features-capture` | git-mode / git-free / rerun capture, `exported_by`, `VMN_EXP_AUTHOR`, show's fact entries |
| B | `similar-backfill` | `vmn-exp similar-backfill`, `core/code_patches.py` |
| M | `mlflow-features` | MLflow tag mapping, `--refresh-features`, `--repo`, client dataset inputs |
| I | `intent-writers` | `--intent`/`--intent-file`, `start_run(intent=)`, `set_intent`, `core/intent.py` |
| L | `similar-cli` | `vmn-exp similar`, the submission hint, `core/similar_search.py`, SDK reader + `Run.similar` |
| U | `similar-ui` | UI routes, run-page card, leaderboard similar mode, rebuilt bundle |
| D | `skill-docs` | the skill section, `agent-skill.md`, the vmn-exp docs, CLAUDE.md, this plan |

Polish rounds fixed review findings in between (launcher-aware entrypoints, symbols
from added/removed lines, linear-time symbol parsing, pasted diffs in commit messages,
lock safety of the local log, the hint's budget bounding its work, malformed intent
keywords).

## 6. Docs

`docs/vmn-exp/experiments.md` (`similar`, the hint, `similar-backfill`, `features`/
`intent` formats, `show --patch`, `--intent*`, import-mlflow flags, `VMN_EXP_AUTHOR`),
`sdk.md` (`start_run(intent=)`, `set_intent`, `similar_runs`, `run.similar`, query
fields), `ui.md` (routes, card, search mode), `server.md` (`/api/v1/similar`),
`migrating-from-mlflow.md` (tag mapping, `--refresh-features`, `--repo`),
`client-guide.md` ("Has anyone run this before?"), CLAUDE.md, and the regenerated
`docs/vmn-exp/agent-skill.md`. Core vmn docs carry none of it.

## 7. Decided differently from the proposal

- Branch: already in `metadata.branch`; not captured into `features` (§1).
- Text: also includes the create entry's `hypothesis` (from `-f`).
- Grouping: by run tree root (whole sweep incl. nested SDK runs) rather than direct
  parent; exclusion drops the target's whole tree.
- Symbols: from hunk headers **and** definitions on added/removed lines (new files and
  functions appended below a hunk context count). A change's function is what git's
  default funcname names (`core/features_scope.py`): any column-0 old-file line in a
  hunk (context, or removed once its change run ends) moves the header's name, empty
  or not (top of the file, only comments above), to it, read as git prints it (first
  80 bytes, up to the first byte that is not UTF-8), so 3-line-context patches name
  what `-U0` does under the default driver, the file's first function included (with
  a `diff=python`-like driver `-U0` can differ); lines past a hunk's `@@` counts
  (format-patch's `-- ` signature) are no changes.
- vmn's own commits (`From: vmn`, left unpushed by an SDK cold start) are skipped:
  `features_from_patches(..., skip_authors=)`, `gitmode/features.py` passes `VMN_USER_NAME`.
- Entrypoint: looks past launcher executables and `python -m` launcher modules.
- Intent: the fold lets a blank text clear it; writers cannot write one.
- No `fold_row` keys for features/intent/hypothesis (side tables), but `author` and
  `has_intent` rows.
- Backfill author: commit `From:` + creating writer; never the base commit's author;
  `changed.untracked` is never backfilled (untracked paths exist only at capture).
- Git-free author-only entries at `features_version: 0`.
- `show` hides `features` from its log; `--json` exposes it as a key.
- Rerun author: the rerunner alone, no commit fallback.
- The hint reads only the persisted index and is skipped above 4000 runs.
- SDK reader keeps the `(app_name=None, ref="latest", *, storage=None, ...)` convention;
  no working-tree target in the SDK.
- `/api/v1/similar` instead of reusing `/api/v1/search`; `all_apps` stays within a
  workspace on the per-workspace routes.
- P0 (§3.7) was added as a prerequisite after a probe showed the data loss.

## 8. Known limits and follow-ups

- Metric streams have the same first-append gap P0 fixed for logs: a fresh root
  appending metrics under a writer whose remote stream exists (`vmn-exp add --metrics`
  from a fresh clone) does not ship the new point (`CachedMetrics._ship_new_blocks`).
- Two clones sharing one writer id that both append and ship concurrently can still
  overwrite each other's segment (sharing a writer id is documented as unsupported).
- A diff pasted into a `--no-stat` format-patch message (no `---` separator) still
  counts as changed; vmn's own capture uses the default format.
- `show`'s text log prints an `intent` entry as its bare type.
- `--dry-run --refresh-features` only counts would-be imports.
- Renormalisation lets a sparse run sharing a single signal score as high as a true
  twin; ties then go to the newest. Tune default weights on a real store (§9).

## 9. Open questions

- Should the default scope be the current app or all apps? (Built: the app for
  `similar` and the hint, `--all-apps` on demand; the UI offers both.)
- Is an author's git email acceptable to show to every viewer of a store? (Built: yes.
  It is already in every commit; the server's roles already gate viewing.)
- Default weights: tune on a real store (the backfill makes that possible on day one).
