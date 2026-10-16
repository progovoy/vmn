# Plan 24: similar runs on SQLite FTS5 (intent search over 100k+ old runs)

> Plan 18 records what an experiment is for (`intent`) and ranks past runs against it.
> Recording is sound. An intent is a log entry of the run, so it syncs, pushes and
> copies with it, and the experiment index folds it into the `intent_of` side table of
> the persisted SQLite cache. Search is not. `core/similar_index.py:SimilarIndex`
> (profiles, postings, a hand-written BM25) is built in memory per snapshot object.
> Only `vmn-exp ui` keeps one alive (`similar_cache.IndexLineages`). Every
> `vmn-exp similar`, `reader.similar_runs` and `run.similar()` call is a fresh process
> and rebuilds it from every run of the app (of every app with `--all-apps`).
>
> Measured 2026-10-16 (Python 3.9, synthetic runs with a 150-word intent, a
> 20k-word vocabulary, one changed file and symbol each; `FakeSnapshot`, so loading the
> experiment index is not included):
>
> | runs | first query (build) | next query, same process | index heap |
> |---|---|---|---|
> | 20k | ~4 s | 0.1 s | ~340 MB |
> | 100k | 14 s | 0.03 s | ~1.6 GB |
>
> The repo's bench (`test_similar_scale_core.py`) stops at 20k runs over 17 words. Other
> limits at scale: the submission hint switches off past 4000 runs
> (`cli/similar_hint.py:MAX_INDEXED_RUNS`), candidates are cut at 5000, and the query
> language can only test `has_intent`.
>
> This plan replaces the in-memory index with a SQLite FTS5 table that is persisted and
> updated per record. FTS5 does candidate selection and ranking in one indexed query,
> so a cold process answers in well under a second at 100k runs with flat memory.
> **No compatibility.** Scores, rankings, reasons and the `--json` item shape may all
> change. The old index, its cache and their tests are deleted, not kept as a fallback.

## 1. Where things live

- The experiment index is one SQLite file per app per store:
  `<cache>/index/<store-id>/<app-slug>.<hash8>.sqlite`.
  - `<cache>` is `$XDG_CACHE_HOME/vmn-exp`; on macOS it is `~/Library/Caches/vmn-exp`,
    else `~/.cache/vmn-exp`.
  - `$VMN_EXP_CACHE_DIR` replaces the base, and the legacy `$VMN_INDEX_CACHE_DIR`
    (`none` = off) replaces the index root.
  - The paths come from `storage/host_dirs.py:index_cache_path`. The CLI, the SDK and
    `vmn-exp ui` share the file (WAL).
- A `vmn-exp ui` server with `db: postgresql://…` caches store workspaces in Postgres
  (`ui/cache_pg.py`).
- **New:** the similar table always lives in the host's SQLite index file, on a
  Postgres-backed server as well. That server keeps a host-local SQLite file per
  workspace app, written from the same index deltas it saves to Postgres. There is one
  search implementation; Postgres `tsvector` is not used. Losing the file costs a
  rebuild, like any cache (plan 11 §2).

## 2. Decisions

- **FTS5 does the search.** One FTS5 table holds a document per run, one column per
  signal. A query is an FTS5 `MATCH` over the target's tokens, ranked by
  `bm25(similar_fts, <column weights>)` in C. Python never scores the corpus.
- **Structured signals are words too.** Changed files, symbols, input digests, dataset
  names, param keys, entrypoint, objective metrics, base commit and branch become
  opaque tokens: a `t` prefix plus 12 hex digits of the sha1 of the old `file:`/`sym:`/…
  token. The default `unicode61` tokenizer then keeps them whole, and identical
  structure matches exactly. Each family gets its own column, so conf
  `experiment.similar.weights` maps one-to-one onto bm25 column weights.
- **Text is FTS5's.** The `text` column (intent text and keywords, note, hypothesis,
  commit subjects) uses `porter unicode61` (stemming: `smoothing` ≈ `smooth`).
  `similar_text.py`'s tokenizer, stopwords and `Bm25` are deleted.
- **Query size is bounded by rarity.** A target run can carry hundreds of tokens.
  The query takes at most 64 per column, the rarest first, by document frequency from
  an `fts5vocab` table. Common tokens add little to bm25 anyway.
- **Ranking in SQL, shaping in Python.** SQL returns the top `PAGE` (500) by bm25.
  Python then drops the target, its run tree and its reruns, applies `--query`,
  archived and app filters on the snapshot rows, groups trees and rerun identities
  (`similar.py`'s grouping), and fetches the next page while fewer than `top` groups
  remain. The 5000-candidate cap is gone.
- **Reasons are computed for the shown items only.** The tokens a target and a result
  share come from per-column intersection of the target's tokens with the result's
  stored token lists (`similar_doc`). That costs a few dozen set operations, not a
  corpus pass.
- **One code path, even without a cache file.** With caching off
  (`VMN_INDEX_CACHE_DIR=none`) or an unwritable dir, the same code runs on a
  `:memory:` SQLite database filled from the snapshot. That is slow, but correct and
  not a second implementation.
- **FTS5 is required.** `similar` checks for it once and exits with
  `similar runs need SQLite with FTS5 (python's sqlite3 lacks it)`. There is no
  fallback scorer. Every CPython build in CI and on macOS/Linux distros has it
  (checked: SQLite 3.51).

## 3. Schema (index `SCHEMA_VERSION` bump to `exp-index-14`)

```sql
CREATE VIRTUAL TABLE similar_fts USING fts5(
  verstr UNINDEXED,
  text,                        -- intent text + keywords, note, hypothesis, commit subjects
  code, files, symbols, inputs, params, entry, objective, branch,
  tokenize = 'porter unicode61'
);
CREATE VIRTUAL TABLE similar_vocab USING fts5vocab(similar_fts, 'col');   -- per-column df
-- the profile a run was filed with: tokens per column (for reasons) + rerun key + root
CREATE TABLE similar_doc (verstr TEXT PRIMARY KEY, rowid_fts INTEGER, data TEXT, version TEXT);
```

The file is per app, so no `app` column is needed. `version` holds
`similar_profile.PROFILE_VERSION`. A mismatch refiles that run on the next refresh,
which is how a tokenizer or profile change rolls out without a schema bump.

## 4. Work units

Each unit runs test-first, in its own worktree, as CLAUDE.md requires.

**F1. Bench + budgets** (`test_similar_scale_core.py`, `@pytest.mark.serial`; rewrite
the 20k/17-word bench). It uses the 100k-run store fixture of
[plan 25](25-database-production-grade.md) F0. If F1 of plan 25 (lean persisted rows)
lands first, F3 here reads candidate rows from `exp_rows`. The corpus uses a 20k-word vocabulary, 150-word intents and
100k runs. Budgets at 100k:
- a cold process answers a full query in ≤ 1 s and a text-only query in ≤ 0.3 s;
- the warm path is ≤ 0.1 s;
- an incremental refresh of 100 changed runs is ≤ 0.2 s;
- extra resident memory is ≤ 150 MB.

Also measure loading the experiment index itself at 100k (`_cached_snapshot`). If that
alone breaks the budget, F3 reads candidate rows by verstr instead of loading the
snapshot.

**F2. Filing** (`core/similar_fts.py`, new; called from `core/index_store.py` `save`
in the same transaction, and from the Postgres server's host-local writer).
- A changed record: `similar_profile.build_profile` → column strings → delete and
  insert its FTS row plus its `similar_doc`. A removed record deletes both.
- A refresh that changes only run states writes nothing.

Tests:
- after a full build, an incremental refresh, a removal and a rewind, the table holds
  exactly one document per current run with its current intent and features;
- a cold process sees a refresh written by another process.

**F3. Querying** (`core/similar.py`, rewritten over `similar_fts.py`;
`core/similar_search.py` keeps its item shaping).
- Build the MATCH expression from the target: rarest-first token selection per column,
  and `--context`/`--text-only` fill the `text` column only.
- Page the bm25 ranking, exclude, filter, group and compute reasons.

Tests:
- known neighbours rank first: same intent keywords, same changed symbol, same dataset;
- the target, its tree and its reruns never appear;
- `--query` and archived filters narrow the results;
- `--all-apps` merges apps by score;
- an FTS-special character in the context (`"`, `*`, `NEAR`, `:`) is quoted, never
  parsed as query syntax.

Rewrite `test_similar_answers_pinned_core.py` against the new ranking.

**F4. Delete and repoint.**
- Delete `similar_index.py`, `similar_postings.py`, `similar_cache.py`, `Bm25` and the
  tokenizer in `similar_text.py`, and their tests (`test_similar_index_*`,
  `test_similar_text_core.py`, `test_ui_similar_reuse.py`,
  `test_ui_similar_parallel_builds.py`).
- `ui/routes_similar.py` reads the same FTS table and no longer holds lineages.
- `cli/similar_hint.py` drops `MAX_INDEXED_RUNS`; its 300 ms deadline becomes a SQLite
  progress-handler interrupt.
- `similar-backfill` refiles what it changes through F2.

**F5. Query language** (`core/query.py`). Add `intent` (the latest intent's text) and
`keywords` (its list; `~` matches any element), read through `intent_of`, plus
`similar("<text>")`: a predicate true for runs whose FTS document matches the words.
The predicate reuses F3's MATCH builder, so a `prune --query` and a UI `?q=` select
by meaning, not substring. Examples: `similar("focal loss imbalance") and status =
"succeeded"`, `keywords ~ "long tail"`. Add these to webui `querySuggest.ts`,
`sdk.md#the-query-language` and the skill.

**F6. Docs.** Update `docs/plans/18-similar-runs.md` §3.3/§4.2 to point here, the
`similar` sections of `experiments.md`/`sdk.md`/`ui.md` (ranking is bm25 over signal
columns; `experiment.similar.weights` are column weights), CLAUDE.md's similar-runs
paragraph, and the skill (regenerate `docs/vmn-exp/agent-skill.md`).

## 5. Out of scope

- Embeddings or any model inside vmn (plan 18 §4: the user's agent supplies meaning).
- Cross-store search (one index per store, as today).
- Moving intent text off the in-memory snapshot side tables. F1 measures whether it
  matters at 100k.
- Reusing the FTS table for the UI's ⌘K run search (`ui/search_index.py`, plan 23 §3.5).
  It is a natural follow-up once F3 lands.
