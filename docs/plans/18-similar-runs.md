# Plan 18: "Has anyone run something like this before?" — similar runs

> A researcher about to run (or looking at) an experiment wants to know which past runs
> — by anyone, in this app or others — were similar, who ran them, when, and how they
> did. Nobody should have to tag runs by hand for this to work.
> Paths are relative to `packages/vmn-exp-sdk/src/vmn_exp/` unless they start with
> `packages/`, `tests/` or `docs/`.

## 1. Decisions

- **Facts on the record, derived data off it.** Things that are true about a run and
  cheap to keep — who ran it, which files/functions the diff touched, the branch, the
  commit subjects — are written into the record, because they are only reliably known at
  submission (branches get deleted, containers run git-free, shallow clones lose history)
  and the record is what travels (`push`, buckets, the server). So is an *intent*
  written by a human or their AI (§4): it is authored text, not something we can
  recompute. Similarity *scores* are never written into records, because they change
  whenever any run is added or the weights change. They live in the rebuildable index, following the
  architecture rule in [README](README.md) ("storage is the source of truth; everything
  else is rebuildable").
- **Features are a `features` log entry, not a `metadata.yml` key.** `metadata.yml` is
  written once by the `create_exclusive` claim and `push` merges only `archived`/`note`, so
  old records cannot be given new metadata safely. Log entries are append-only per writer,
  already synced/pushed, and are how tags and rewinds already add to old runs. New runs
  write the entry next to their `create` entry; backfills append it with their own
  writer. There is one rule: the fold keeps the entry with the highest `features_version`,
  and the latest of those wins.
- **vmn never needs an AI model.** v1 = structured features + a weighted score + the
  reason each run matched. v2 = the user's own AI (any agent, any model) reads the diff and
  writes an *intent* (`--intent-file` / `--context-file`); vmn stores it on the record and
  matches it lexically, and the agent re-ranks the candidates it gets back. A skill
  teaches agents this loop. No embedder, vectors or network calls inside vmn.
- **Ask before submitting.** `vmn-exp similar <app>` with no ref uses the current
  working tree's features, so you can check before creating a run.

## 2. What "similar" is made of

| Signal | Source | Already on record? | Similarity |
|---|---|---|---|
| Author | `actor_identity()` at creation (§3.1) | **no** — `run_state` has `host` only (`packages/vmn-exp/src/vmn_exp/cli/run.py:338`); `actor_identity()` already attributes registry writes (`actor`), comments and reports, never runs | shown, not scored (row field `author`, filter with `--query`) |
| Base code | `code_verstr` (base version + commit) | yes | same commit 1.0; same base version 0.7; version distance decays (git-free proxy for ancestry) |
| Changed files | snapshot patches | no (derivable from the code object) | Jaccard |
| Changed symbols | unified-diff hunk headers (`@@ … @@ def focal_loss`): git's own function detection, any language | no (derivable) | Jaccard, weighted above files |
| Commit subjects | local commits in the snapshot's format-patch `Subject:` lines | no (derivable) | part of the `text` signal only |
| Branch | `git rev-parse --abbrev-ref HEAD` at creation | no | equality |
| Inputs | `row["inputs"]` (uri/digest/kind), registry `<name>@<N>` | yes | same digest 1.0; same dataset name, other version 0.6 |
| Params | `row["params"]` | yes | key Jaccard × mean value closeness (numeric: `1 - min(1, \|log10(a/b)\|/2)`; others: equality) |
| Entrypoint | `run_state.command` (argv) | yes | same script; same script + subcommand |
| Objective | metric names + effective schema `goal` | yes | Jaccard over metric names |
| Text | name, note, tags, commit subjects; v2 adds the `intent` entry (§4.1) | name/note/tags yes | one `text` signal: BM25 (§4.2), already in v1 over the fields v1 has |

Default weights live in `core/similar_score.py`; conf `experiment.similar.weights.<signal>`
overrides them. A signal missing on either side is left out of the score (renormalised),
not counted as 0, so imported MLflow runs (no code) are still comparable on
params/inputs/objective.

## 3. v1 — structured similarity

### 3.1 Formats

```yaml
# log entry, writer = the run's writer (new runs) or "features" (backfill)
type: features
features_version: 1
source: capture | backfill | mlflow     # where these facts came from
author: {writer: gpu-07, git_user_email: a@x.io, os_user: alice, source: git | export | env | commit | mlflow}
branch: feat/focal-loss                  # null when detached / git-free
changed:
  files: [src/loss.py, src/train.py]
  symbols: ["src/loss.py::focal_loss", "src/train.py::train_step"]
  untracked: [notes/idea.md]             # paths only, never contents
commits: ["try focal loss gamma=2", "wire loss into trainer"]
```

- `core/features.py` (pure): `features_from_patches(patch_texts, untracked_paths) ->
  dict` (parses `diff --git`, `@@ … @@ <context>`, `Subject:`; caps: 200 files, 500
  symbols, 50 commits; `truncated: true` when it cuts).
- `author` reuses `actor_identity()` (`registry/log.py`, the shape registry `actor`, comments
  and reports already store) plus `source`, so every "who" in the product renders the same
  way. Move it to `core/identity.py` (re-exported from `registry/log.py`) so core does not
  import the registry. `writer` and `os_user` are always filled by it; `git_user_email`
  falls back: git config → the exporter's email in `vmn_metadata.yml` (git-free runs from
  `vmn-exp export`) → `VMN_EXP_AUTHOR` (new env var; document it) → the `From:` of the
  snapshot's first local commit; `source` names the one used.

### 3.2 Writing them at submission

- Git mode: `packages/vmn-exp/src/vmn_exp/gitmode/` already holds the capture
  (`SnapshotCapture`, patches) outside the lock; compute features there and pass them to
  `writer.create_run` (new `features=` arg → a `features` entry appended with the
  `create` entry). The branch read goes through `version_stamp.api` (import rule: vmn-exp
  reaches vmn only through `api`); no new vmn-core API is needed for the author.
- Git-free (`core/from_snapshot.py`): features from the exported snapshot's patches +
  `vmn_metadata.yml` author.
- Rerun (`cli/rerun.py`) calls `create_run` without a capture: it copies the original's
  `features` (same code) with the rerunner's `author`. Fork captures its own features
  (`features`/`intent` stay out of `core/fork.py:INHERITABLE`); its intent is not inherited.
- `vmn snapshot` records are not runs; out of scope.
- Best-effort like `env`: a failure logs a warning and the run is created without the entry.

### 3.3 Index

- `core/fold.py`: `_apply_features` (highest `features_version`, then latest by fold key).
- `IndexSnapshot.features_of(verstr)` — a side table like `outputs_of` (kept off lean rows,
  so list/leaderboard payloads don't grow). Bump `index_store_schema.SCHEMA_VERSION`.
- `core/similar_index.py`: an inverted index `token -> verstrs` over `file:`, `sym:`,
  `input:<digest>`, `ds:<name>`, `pkey:`, `cmd:`, `metric:` tokens, built from the snapshot.
  Candidates = runs sharing ≥1 token (cap 5k by token rarity), then scored. No
  O(n²) work, nothing persisted beyond the index cache.
- `core/similar_score.py` (pure): `score(a, b, weights) -> (float, reasons)`; reasons are
  the top contributing signals rendered as `same dataset imagenet@3`, `2 shared
  functions: loss.py::focal_loss, …`, `lr 3e-4 vs 1e-4`.
- `core/similar.py`: `similar_runs(snapshot, target_features, top, query=…, exclude=…)`;
  the target is a row or features from the working tree. The target's own `code_verstr`
  and sweep are excluded, and candidates are grouped by `code_verstr` and by sweep (outer
  run): each group shows its best run by the goal metric, plus `(+N runs)`, so sweep siblings
  and repeats of the same code cannot fill the list.
- Row fields `author` (`git_user_email`, else `os_user`) and `has_intent` (v2) join the
  query language, so filters reuse `--query` instead of new flags.

### 3.4 Surfaces

- CLI `vmn-exp similar <app> [-v <ref> | --latest] [--top 10] [--all-apps] [--query
  <expr>] [--json]` (`packages/vmn-exp/src/vmn_exp/cli/similar.py`). Read-only (add to
  `READ_ONLY_ACTIONS`). No ref = the current working tree (capture without creating a run).
  Unlike `show`/`restore`/`export`, where no ref means the latest run, this follows `vmn
  snapshot diff` (default: the working state); the help text and docs say so explicitly.
  Output: `<verstr>  <score>  <author>  <age>  <status>  <goal metric>=<v>  — <reasons>`.
- Submission hint: `vmn-exp run` and `create` print the top 3 after the claim, before the
  child starts: `3 similar runs: best val_loss=0.31 — t7 by alice@x.io, 3 weeks ago (same
  dataset, focal_loss changed)`. Uses the local index cache only, with a 300 ms budget, and
  is skipped silently when the cache is cold. It is not computed for sweep trials or other
  inner runs (`VMN_SWEEP_TRIAL` / a parent set), which would otherwise pay the budget and
  print siblings on every trial. Opt out with `--no-similar` / conf
  `experiment.similar.hint: false`. The SDK only logs it at debug level (it must not
  print into training stdout).
- SDK `vmn_exp.sdk.reader.similar_runs(app, ref=None, top=10)`, `run.similar(top=)`.
- UI `GET .../experiments/{verstr}/similar?top=&all_apps=` (all-apps mode reuses
  `routes_search.py`'s per-workspace viewability); a "Similar runs" panel on run detail
  (`webui/src/components/`), with the reasons shown as chips.

### 3.5 Re-deriving features

`vmn-exp similar-backfill <app> [--all-apps] [--dry-run] [--store …]`: a separate writing action, so `similar` stays purely read-only (no `watch --compact`-style exception at `cli/experiment.py:294`).

It is not a one-off migration. It selects every finished run without a `features` entry at
the **current** `features_version`, which covers:
- runs whose best-effort capture at submission failed (no entry at all);
- runs captured by an older version, after a release adds or changes a signal and bumps
  `features_version`;
- runs recorded before this plan shipped.

Descriptions are a different path: a run submitted without a comment still gets its
features at submission, and its intent is added later with `vmn-exp add --intent-file` (§4).

- Load **only the patches** of the run's code object (not the untracked tarball), call
  `features_from_patches`, and append a `features` entry (`source: backfill`) under this
  host's normal writer id (`get_writer_id()`, like `tag`/`rewind`). A fixed writer name
  would make two hosts backfilling the same remote run write the same
  `log/<writer>@<seq>` files.
- When the run already has an older entry, only the patch-derived fields (`changed`,
  `commits`) are recomputed. `author` and `branch` are carried over from it unchanged:
  they were observed at submission and cannot be re-derived as well. Without an older
  entry the author comes from the patches' `From:`; if a git checkout is present, the base
  commit's author is used instead (`author.source: commit`).
- Runs that share a code object share the computation (memo by `code:` key).
- Idempotent (a run at the current version is skipped), resumable by construction, takes
  the repo lock like `tag`/`rewind`, works git-free. Running/stuck runs are skipped.
- Runs whose code object is missing get features derived from their record only (no
  `changed`), and are counted as `partial` in the summary:
  `backfilled N, partial P, skipped S, failed F`.

### 3.6 MLflow imports

The importer (`packages/vmn-exp/src/vmn_exp/importers/import_records.py`) already maps
params, metrics, user tags and datasets (as inputs with digests), so input/param/objective
similarity works for imported runs as soon as v1 lands. It drops every `mlflow.*` tag,
which includes the fields we need:

| MLflow tag | Goes to |
|---|---|
| `mlflow.user` | `features.author` (`source: mlflow`) |
| `mlflow.note.content` | record note (via the create entry; `--refresh-features` appends a `note` entry). Already part of the `text` signal, so it is not copied into `intent` |
| `mlflow.source.git.branch` | `features.branch` |
| `mlflow.source.name`, `mlflow.project.entryPoint` | `imported_from.source_name` / entrypoint signal |
| `mlflow.source.git.repoURL` | `imported_from.repo_url` |

- New imports write a `features` entry (`source: mlflow`) built from those tags.
- **Already-imported runs:** `import_run` returns `skipped` before reading anything, and
  the dropped tags exist only in MLflow. Add `import-mlflow … --refresh-features`: for
  `skipped` runs with no `features` entry, append one built from the source tags (the source
  must still be reachable). Nothing else is rewritten.
- Code signal: MLflow keeps no diff. If `imported_from.source_commit` exists in a local
  checkout (`--repo <path>`), `changed` = the files and symbols of
  `git diff $(git merge-base <default branch> <commit>) <commit>`, marked `source:
  commit` with half weight (it is a branch's cumulative change, not the run's own diff).
  Without a checkout, this signal is left out.

## 4. v2 — bring your own AI: intent text from the user's agent

vmn ships no model and calls none. The semantic work (reading a diff and writing down
what an experiment is *for*) is done by whatever AI the user already runs — Claude Code,
Cursor, a CI script calling any API — through plain CLI calls. vmn stores the result as a
fact on the record and matches it deterministically. A skill teaches agents the loop.

### 4.1 The `intent` entry

```yaml
# log entry; latest wins (fold side table intent_of, like features_of)
type: intent
text: |                       # markdown, capped at 16 KB (truncated: true past it)
  Hypothesis: focal loss (gamma=2) fixes the minority-class recall drop seen in t4.
  Changed: src/loss.py::focal_loss (new), src/train.py::train_step uses it.
  Data: imagenet-lt@3. Expect: val_recall_min up, val_loss roughly flat.
keywords: [focal loss, class imbalance, long tail, reweighting, gamma]   # <= 50
generator: claude-opus-5-5    # optional free string; absent = written by a human
source: user
```

Written through:
- `vmn-exp create|run <app> --intent "<text>" | --intent-file <path|->`. A file may start
  with YAML front matter (`keywords:`, `generator:`); the rest is the text.
- `vmn-exp add <app> -v <ref> --intent-file <path|->`: add or replace an intent later (this
  is also how old runs are backfilled). It takes the repo lock like `tag`.
- SDK `start_run(intent=…, intent_keywords=…)`, `run.set_intent(text, keywords=, generator=)`.

It is not the `note`: the note stays the short one-liner `list` shows, while the intent is
the long description used for matching. An agent may set both.

### 4.2 Matching text without a model

- `core/similar_text.py` (pure): BM25 over each run's text document (intent text,
  keywords ×3, name, note, tags, commit subjects), with `w:` tokens in the §3.3 inverted
  index. Changed symbols stay structured only, so nothing is counted twice. It is the
  single `text` signal in `similar_score`. v1 already scores it over the fields v1 has;
  intents raise its default weight to code + inputs combined. Its reasons show
  the shared keywords (`shared: focal loss, class imbalance`).
- Lexical matching is enough because the agent expands synonyms twice: once in the
  keywords it writes onto each run, and once in the query it sends. Semantic judgement
  happens in the agent, which re-ranks the candidates it gets back (§4.3).
- No embeddings, vector cache, plugin or network calls. The UI and server use the same
  scorer from the index.

### 4.3 Querying with context

- `vmn-exp similar <app> --context "<text>" | --context-file <path|->`: a text query.
  It is combined with the target's features: the working tree without `-v`, the run with
  `-v`; the context text replaces that target's text document. `--text-only` drops the
  features, for questions like "has anyone tried label smoothing?".
- `--json` gives an agent everything it needs to re-rank and answer, with no further
  calls: per candidate `verstr, app, score, reasons, author, timestamp, status, goal
  metrics, note, intent (first 2 KB), features`.
- `vmn-exp show <app> -v <ref> --patch [--max-bytes N]`: print a run's own patches (`show`
  already loads them for `patch_lines`, `cli/views.py:28`). The agent uses this to inspect a
  candidate, or to write an intent for an old run. MLflow runs have no code, so it prints
  a one-line note instead of failing.
- Backfill worklist: `vmn-exp list <app> --query "has_intent = false and status =
  succeeded" [--last N] --json`. This is the existing list/query path, not a new flag.
- UI: the run-detail "Similar runs" panel shows the intent. Free text is a "similar" mode
  of the existing search box (`webui/src/util/searchQuery.ts`, which today sends the query
  language to `/api/v1/search?q=`), not a second box. That mode calls `GET
  /api/v1/similar?text=` with the same scorer (`--text-only` semantics).

### 4.4 The skill (`vmn-exp skill`, `packages/vmn-exp/src/vmn_exp/cli/skill.py`)

A new "Similar experiments" section, so any agent that installed the skill does this
without being prompted:

1. **Before submitting a run:** read the change (`git diff HEAD`, unpushed `git log`)
   and write `intent.md`: hypothesis, which functions changed and why, key params,
   dataset, expected effect. Use front matter `keywords:` with synonyms and the
   problem's usual names, and `generator: <your model id>`. Describe the change, not
   results. Never paste secrets or data, and stay under ~2 KB.
2. `vmn-exp similar <app> --context-file intent.md --all-apps --json`. Read the top
   candidates (`show --patch` for the 1–3 closest) and tell the user who ran what, when,
   how it scored, and how this run differs. Re-rank on meaning, not just the score.
3. Submit with `--intent-file intent.md` (CLI) or `start_run(intent=…)` (SDK).
4. **Backfilling when asked:** take `vmn-exp list <app> --query "has_intent = false" --json`
   (narrow with `--last`/more `--query` terms to bound the cost), and for each run do `show -v <ref> --json --patch`, write an intent,
   then `vmn-exp add <app> -v <ref> --intent-file -`.
5. **For questions** ("did anyone try X?"): `similar --context "<X plus synonyms>"
   --text-only --all-apps --json`, then answer citing verstrs.

`docs/vmn-exp/agent-skill.md` is regenerated from it (never hand-edited).

### 4.5 Migration for v2

- Old vmn runs: their structured features come from the §3.5 backfill. Intents come from
  the skill's backfill loop (step 4), run by the user's agent at whatever scope and cost
  they choose. Runs without an intent still match on everything else.
- MLflow runs: their note (imported, or added by `--refresh-features`) already feeds the
  `text` signal. An agent can then add an intent to them
  through the same loop (`show --patch` falls back to params/datasets when there is no code).
- Privacy: vmn never sends anything anywhere. Whatever leaves the machine is the user's
  agent's choice, which keeps air-gapped use intact.

## 5. Phases (TDD; parallel worktrees where independent)

| Phase | Worktree | Content | Depends on |
|---|---|---|---|
| 1a | `features-core` | `core/features.py` (patch parsing, caps) + `fold._apply_features` + `features_of` side table + schema bump | — |
| 1b | `similar-score` | `core/similar_score.py`, `core/similar_index.py`, `core/similar.py`, `core/similar_text.py` (BM25 `text` signal over name/note/tags/commit subjects) (pure, row fixtures) | — |
| 1c | `features-capture` | gitmode + `from_snapshot` write the entry; `actor_identity()` → `core/identity.py` + email fallbacks; rerun copies features | 1a |
| 1d | `similar-cli` | `vmn-exp similar` (`--query`, grouping), run/create hint (skipped for inner runs), SDK reader, `author` row field, read-only registration | 1a, 1b |
| 1e | `similar-backfill` | `vmn-exp similar-backfill` action: runs below the current `features_version` (host writer id, patch-only code load, author/branch carried over, memo, summary) | 1a |
| 1f | `mlflow-features` | importer tag mapping (note → note), `--refresh-features`, `--repo` commit diff | 1a |
| 1g | `similar-ui` | route + run-detail panel | 1d |
| 2a | `intent-entry` | `intent` log entry + fold side table, `--intent`/`--intent-file` (front matter) on create/run/add, SDK `intent=`/`set_intent`, `has_intent` row field | 1a |
| 2b | `similar-text` | intent text + keywords in the `text` document, `--context`/`--context-file`/`--text-only`, JSON fields, `/api/v1/similar?text=` + search-box mode | 1b, 2a |
| 2c | `show-patch` | `vmn-exp show --patch [--max-bytes]` (no-code runs: params/datasets note) | — |
| 2d | `similar-skill` | "Similar experiments" section in `cli/skill.py`; regenerate `docs/vmn-exp/agent-skill.md` | 2a–2c |

Docs: `docs/vmn-exp/experiments.md` (CLI + `features` entry), `sdk.md` (`similar_runs`),
`ui.md` (routes), `migrating-from-mlflow.md` (`--refresh-features`), CLAUDE.md command
summary + `VMN_EXP_AUTHOR` in its env-var list; regenerate `docs/vmn-exp/agent-skill.md` (2d changes `cli/skill.py`).

## 6. Open questions

- Should the default scope be the current app or all apps? (Proposal: the app for the
  submission hint, with `--all-apps` on demand; the UI offers both.)
- Is an author's git email acceptable to show to every viewer of a store? (Proposal: yes. It
  is already in every commit; the server's roles already gate viewing.)
- Default weights: tune on a real store before release (the backfill makes that possible on
  day one).
