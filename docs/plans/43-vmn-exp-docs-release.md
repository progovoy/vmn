# Plan 43: vmn-exp review fixes, positioning, docs, packaging and release discipline

> Workstream F of the 2026-11-11 vmn-exp product review. The index, the
> milestone order, the cross-stream conflicts and the owner decisions are in
> [37-vmn-exp-review-fixes.md](37-vmn-exp-review-fixes.md). Each item was drafted by a
> planner that read the code, then revised by a critic that re-checked the
> evidence and looked for tests pinning today's behaviour.
>
> Sizes: S under a day, M 1-3 days, L about a week, XL more. Priorities: P0 security or data loss, P1 blocks adoption or misleads users, P2 quality, P3 nice to have.

Status: **proposed** (2026-11-11). Owner decisions of 2026-11-11 are applied in this file. Evidence was re-read at `59becdd5` (26 commits after the draft's `25f03f3d`).

Solo impact: see each item's risk line; nothing here may make the single-user case worse. F13 is the item that pins it.

## Summary

Sixteen items. Nothing is implemented. The owner's answers changed six items and added three:

- **Releases stay 0.1.x patch releases (F9).** No breaking batch is saved up for a minor release, and nothing triggers a minor. F9 is now the rule set for patch-only releasing: every behaviour change lands with an `upgrading.md` row and a changelog entry; a deprecation is removed no sooner than 10 releases and 30 days after its row (both numbers proposed, owner to confirm); a store-layout, record-format or full-reload index change is announced one release ahead and ratcheted by a test. `release_exp.sh` keeps its patch-only shape.
- **The HTTP API moves out of `ui.md` (F5).** `docs/vmn-exp/ui-api.md` takes lines 837-1967 of today's `ui.md`. F5 lists the two test lines, the 13 cross-doc links, the 16 in-file links and the index lines that move with it.
- **Both exp packages require Python >=3.10 (F12).** This drops 3.8 and 3.9 job images in a patch release, so F12 starts by reading the interpreters real runs recorded and carries an `upgrading.md` row.
- **F13 is written against the new default board.** Plan 38 A6 was decided as: an app with no outer runs opens on the runs board. F13 pins the two server answers that board reads.
- **F15 (web tests in CI) is now plan 42 E14a**, a blocking stage with ESLint after a one-off fix pass.
- **F14 is the roadmap decision record**, and its three "build" answers are drafted here as F16 (LightGBM and CatBoost autolog), F17 (ASHA early stopping) and F18 (a notebook repr for the run object).
- F10 (changelog regenerated after upload) and F11 (keep the `==` pin, one golden record per format) are decided as written here. F1/F2 publish measured facts with their cost.

**What upstream changed since the draft.** The 26 commits touch none of this workstream's subjects: no item is done upstream. `ui.md` grew by 38 lines, so every `ui.md` line number below is re-read (the broken link is at `:450`, the API starts at `:837`, `### Similar runs` is at `:1857`). `ui/thread_limiters.py` is new (cddf6651) and exists only because anyio for Python 3.9 stops at 4.12; F12 names it. The two review fixes (859da19b in `ui/jobs.py`, 59becdd5 in `storage/buffered.py`) are outside this workstream.

**Confirmed again at HEAD**
- `ui.md:450` is the only broken relative link in the scanned docs.
- The `==` SDK pin must stay: vmn-exp imports SDK-internal modules, some by private name, from the same PEP 420 namespace.
- 39 `vmn_exp_*` tags exist (0.0.0 plus 38 releases, 2026-09-28 to 2026-11-10); the 38 releases fall on 16 days, 12 of them on 2026-10-22.
- No `CHANGELOG.md`, `cliff.toml` or `upgrading.md` exists yet.

**Not verified**
- The live PyPI state.
- Which interpreters client job images run. The repo cannot say; each store can (F12 step 1).
- How git-cliff orders these tags (F10's real-git test settles it).
- LightGBM's and CatBoost's attribute shapes (F16 is designed from the adapter contract in this repo and from the libraries' documented scikit-learn API; its real-library tests settle it).

Order: F4 first as the guard, then F1/F2, then F5. The release chain is F9 → F10 → F11 → F12. F8 → F13/F14 run alongside. F16, F17 and F18 are independent features and come last; F18 pairs with plan 38 A9.

## Items

| Id | Pri | Size | Item | Owner decision |
|---|---|---|---|---|
| [F4](#f4) | P2 | S | Docs link, anchor and index checker; fix the broken ui.md -> experiments.md#nesting link |  |
| [F1](#f1) | P1 | S | Replace the 'No server, no database' headline with the current architecture rule | decided |
| [F2](#f2) | P1 | S | Refresh the stale rows of vmn-vs-mlflow.md and the scale wording (measured facts with their cost) | decided |
| [F3](#f3) | P2 | M | Add docs/vmn-exp/vmn-vs-wandb.md |  |
| [F5](#f5) | P2 | M | Split the HTTP API out of ui.md into ui-api.md; a table of contents in both | decided |
| [F6](#f6) | P3 | S | experiments.md: use the vmn-exp command names; one home for the stuck formula and for install |  |
| [F8](#f8) | P2 | M | Bring docs/plans/README.md and the plan Status lines up to date, with a consistency test |  |
| [F9](#f9) | P1 | M | Patch-only release rules: upgrading.md, the removal rule for deprecations, and a format-version ratchet | decided |
| [F10](#f10) | P1 | M | Generated CHANGELOG.md for vmn-exp: git-cliff scoped to the two exp packages, regenerated after each upload | decided |
| [F11](#f11) | P2 | M | State and test the SDK/server compatibility contract; keep the == pin; one golden record per format | decided |
| [F12](#f12) | P2 | M | Both exp packages require Python >=3.10; pyproject metadata, bounded extras, and the stale PyPI section of packaging.md | decided |
| [F13](#f13) | P2 | S | Protect the solo-user experience: a small-store contract test on the new default board and a 'Solo impact' line in every plan from 37 on | decided |
| [F14](#f14) | P2 | S | Roadmap decision record for the feature gaps | decided |
| [F16](#f16) | P2 | M | LightGBM and CatBoost autolog | decided |
| [F17](#f17) | P2 | M | ASHA early stopping for sweeps | decided |
| [F18](#f18) | P3 | S | A notebook repr for the run object | decided |

<a id="f4"></a>
### F4. Docs link, anchor and index checker; fix the broken ui.md -> experiments.md#nesting link

P2 · S

**Problem.** docs/vmn-exp/ui.md:450 links to experiments.md#nesting, but experiments.md has no such heading or anchor; the settled-runs text is under '## Outer & inner jobs (sweeps)' (experiments.md:375), whose slug is outer--inner-jobs-sweeps (experiments.md:175 and ui.md:486 already link it that way). No test checks doc links. A scan of docs/vmn-exp/*.md, docs/packaging.md, docs/plans/README.md and the two package READMEs during this review found exactly this one broken relative link, so the test is red for one reason only.

**Approach.**

New test-support module packages/vmn-exp/tests/doc_links.py with two pure functions over text: heading_slugs(text) (GitHub slug rules, duplicate suffixes, headings inside code fences skipped the way _section does in test_docs_similar_statements.py:35-37) and broken_links(docs: dict[path, text]) returning (source, line, target) for relative links whose file or #anchor is missing. Links inside code fences and absolute URLs are ignored; no network. A third pure function, unlinked_docs(index_text, filenames), reports a doc the index does not link; F3, F5 and F9 each add a doc and rely on it. Then fix ui.md:450 to experiments.md#outer--inner-jobs-sweeps. Real-files scope: docs/vmn-exp/*.md, docs/packaging.md, docs/plans/README.md, packages/vmn-exp/README.md, packages/vmn-exp-sdk/README.md. The real-files scope is a glob, so ui-api.md (F5), upgrading.md (F9), vmn-vs-wandb.md (F3) and notebooks.md (plan 38 A9) are checked from the day they exist. Keep the module under 120 lines; no general markdown parser.

**Tests first.**

- packages/vmn-exp/tests/test_docs_links.py::test_slug_matches_github_for_punctuation_and_backticks (in-memory: '## Outer & inner jobs (sweeps)' -> 'outer--inner-jobs-sweeps'; '### `similar`' -> 'similar')
- test_docs_links.py::test_a_link_to_a_missing_anchor_is_reported (in-memory dict of two docs)
- test_docs_links.py::test_headings_and_links_inside_code_fences_are_ignored
- test_docs_links.py::test_the_vmn_exp_docs_have_no_broken_relative_links (real files; red today on ui.md:450 only)
- test_docs_links.py::test_a_doc_missing_from_the_index_is_reported (in-memory text)
- test_docs_links.py::test_the_docs_index_links_every_vmn_exp_doc (real files; green today with 14 docs, red as soon as a new doc exists unlinked)

**Files.** `packages/vmn-exp/tests/doc_links.py`, `packages/vmn-exp/tests/test_docs_links.py`, `docs/vmn-exp/ui.md`

**Risk.** No runtime change. The slug function must match GitHub for the headings this repo uses (backticks, '&', parentheses, '/'); the in-memory tests pin those cases. Reading real doc files is the same thin IO the existing docs tests do.

**Evidence.** `docs/vmn-exp/ui.md:450`; `docs/vmn-exp/ui.md:486`; `docs/vmn-exp/experiments.md:175`; `docs/vmn-exp/experiments.md:375`; `packages/vmn-exp/tests/test_docs_similar_statements.py:30-45`

<a id="f1"></a>
### F1. Replace the 'No server, no database' headline with the current architecture rule

P1 · S

**Problem.** New readers are told there is no server and no database (docs/vmn-exp/README.md:5-6, experiments.md:5, vmn-vs-mlflow.md:19 and :113), while server.md documents server.yml, a SQLite/Postgres cache, OIDC and roles, and docs/plans/README.md records that the rule was replaced by 'storage is the source of truth ... training never depends on the server'. PRODUCT.md:24 already uses the correct wording ('no server or database is required').

**Approach.**

Docs only. docs/vmn-exp/README.md gets the decided headline: **storage is the source of truth; training never depends on a server.** One sentence follows it: no server or database is required to record or read runs, and the optional team server (server.md) keeps only a rebuildable cache. experiments.md:5 and vmn-vs-mlflow.md:19 and :113 change 'no server, no database' to 'no server or database required' and link server.md. Do not copy PRODUCT.md:24's 'hosted control plane' sentence into the docs: PRODUCT.md:51 forbids hosted-availability claims. Leave alone, because they are true as written: README.md:7 (core vmn), reports.md:5-7 ('They have no database', about reports), skill.py:14 / agent-skill.md:5 ('without a server', about tracking).

**Tests first.**

- packages/vmn-exp/tests/test_docs_positioning.py::test_absolute_no_server_claims_are_reported (pure absolute_claims(text) helper on in-memory text: flags 'No server, no database' and 'There is no server and no database'; does not flag 'no server or database is required', 'without a server', 'They have no database')
- test_docs_positioning.py::test_no_vmn_exp_doc_makes_the_absolute_claim (docs/vmn-exp/*.md; red today on three files)
- test_docs_positioning.py::test_the_docs_index_links_server_md_beside_the_storage_rule

**Files.** `docs/vmn-exp/README.md`, `docs/vmn-exp/experiments.md`, `docs/vmn-exp/vmn-vs-mlflow.md`, `packages/vmn-exp/tests/test_docs_positioning.py`

**Risk.** None at runtime. The ban is limited to the two absolute phrasings so it cannot flag the true sentences listed above. docs/vmn-exp/agent-skill.md is generated from skill.py and is not edited.

**Owner decision (2026-11-11).** The headline is "storage is the source of truth; training never depends on a server".

**Evidence.** `docs/vmn-exp/README.md:5`; `docs/vmn-exp/experiments.md:5`; `docs/vmn-exp/vmn-vs-mlflow.md:19`; `docs/vmn-exp/vmn-vs-mlflow.md:113`; `docs/plans/README.md (Architecture rule paragraph at the end)`; `PRODUCT.md:24`; `docs/vmn-exp/reports.md:5-7`; `packages/vmn-exp/src/vmn_exp/cli/skill.py:14`

<a id="f2"></a>
### F2. Refresh the stale rows of vmn-vs-mlflow.md and the scale wording (measured facts with their cost)

P1 · S · depends on F1

**Problem.** vmn-vs-mlflow.md contradicts the other docs: 'locally or in S3' (:20) against its own table row 'local filesystem, S3, GCS or Azure Blob' (:47); 'Plugin ecosystem: None' (:55) against the storage plugin contract (experiments.md:1752-1756, ENTRY_POINT_GROUP in storage/registry.py:22); scale 'the UI stays fast at ~100k runs per app' and 'we have not tested at the run counts a DB-backed MLflow serves' (:56, :168-169) against the 737k-run store measured in ui.md:256-259; 'Server required: Yes, for any real deployment' (:48) is loaded; there are no sources or as-of date. The same promise is repeated in architecture.md:350-351 ('the leaderboard answers from memory even at 100k runs') and in PRODUCT.md:30 ('built to stay fast at ~100k runs') and :58 ('Thousands to 100k runs').

**Approach.**

Docs only. vmn-vs-mlflow.md:20 becomes 'locally or in an object store (S3, GCS, Azure)'. Plugin row: 'Storage backends through the vmn_exp.storage entry point; no wider ecosystem'. Server row: describe MLflow neutrally ('tracking server + database for shared use; a local file store for one user'). Add a Sources section with the MLflow doc links, the MLflow version and the date checked; the implementer re-checks every MLflow cell against current MLflow docs.

Scale, everywhere, is the measured facts with their cost and no 'stays fast at N' promise:
- the load harness: 100k runs, 500 live jobs, 16 clients; list p50/p95 3.5/70 ms and 299 requests/s on 3.14t, 247/761 ms and 42 requests/s on 3.14 with the GIL (ui.md:261-269);
- one 737k-run S3 store: 18 GB RSS on 3.15.2t loading from the built index, warm board pages about 10 ms, an outer run's summary 0.1 to 0.2 s; a cold index took 112 GB RSS on 3.14 and 74 GB on 3.14t (ui.md:256-259).

ui.md keeps the numbers; the other places state one sentence and link to it:
- vmn-vs-mlflow.md:56 (table row) and :168-169 (section);
- architecture.md:350-351: 'keeps those rows in an index cache, so the leaderboard answers from memory; measured sizes and their memory cost are in ui.md';
- PRODUCT.md:30: 'Watched apps can be large: measured at 100k runs in the load harness and on one 737k-run store (docs/vmn-exp/ui.md), at a memory cost that grows with the store';
- PRODUCT.md:58 principle 4: 'Thousands to hundreds of thousands of runs and live fleets of jobs are expected'.

**Tests first.**

- packages/vmn-exp/tests/test_docs_positioning.py::test_a_speed_promise_at_a_run_count_is_reported (pure scale_promises(text) on in-memory text: flags 'stays fast at ~100k runs', 'even at 100k runs', 'in milliseconds at ~100k runs'; does not flag 'about a minute per 100k runs' or 'measured at 100k runs')
- test_docs_positioning.py::test_no_vmn_exp_doc_promises_speed_at_a_run_count (docs/vmn-exp/*.md; red today on vmn-vs-mlflow.md and architecture.md)
- test_docs_positioning.py::test_the_mlflow_comparison_names_every_built_in_object_store (ties the doc to code: each remote scheme in storage.registry.STORAGE_EXTRAS has its product name in the overview paragraph; red today on :20)
- test_docs_positioning.py::test_the_mlflow_comparison_names_the_storage_entry_point_group (registry.ENTRY_POINT_GROUP appears in the doc; red today)

**Files.** `docs/vmn-exp/vmn-vs-mlflow.md`, `docs/vmn-exp/architecture.md`, `PRODUCT.md`, `packages/vmn-exp/tests/test_docs_positioning.py`

**Risk.** MLflow claims were not re-checked in this pass. The 737k figure is already public in ui.md:256, so linking it reveals nothing new. The scale_promises patterns are three phrasings, not a general ban, so measured sentences such as server.md:176 ('about a minute per 100k runs') stay legal. PRODUCT.md is outside docs/vmn-exp and is not scanned by the test; its two lines are edited by hand.

**Owner decision (2026-11-11).** Publish measured facts with their cost, in the comparison, in architecture.md and in PRODUCT.md:30/:58. No 'stays fast at N' promise.

**Evidence.** `docs/vmn-exp/vmn-vs-mlflow.md:20`; `docs/vmn-exp/vmn-vs-mlflow.md:47-48`; `docs/vmn-exp/vmn-vs-mlflow.md:55-56`; `docs/vmn-exp/vmn-vs-mlflow.md:168-169`; `docs/vmn-exp/architecture.md:349-351`; `docs/vmn-exp/ui.md:256-269`; `docs/vmn-exp/experiments.md:1752-1756`; `packages/vmn-exp-sdk/src/vmn_exp/storage/registry.py:22`; `packages/vmn-exp-sdk/src/vmn_exp/storage/registry.py:33`; `docs/vmn-exp/server.md:176`; `PRODUCT.md:30`; `PRODUCT.md:58`

<a id="f3"></a>
### F3. Add docs/vmn-exp/vmn-vs-wandb.md

P2 · M · depends on F1, F2, F4

**Problem.** There is no W&B comparison, although the docs lean on W&B as the reference (sweeps.md:3-4 'in the style of W&B Sweeps', sdk.md:394 'run.alert() is wandb.alert()', the plans index is titled 'MLflow / W&B adoption plans'). The importers package holds only MLflow modules. Plan 20 is about dashboard flows and plans no importer, so the importer was a roadmap decision, not a missed commitment; F14 records it as deferred.

**Approach.**

Docs only, same structure as the refreshed vmn-vs-mlflow.md: overview, feature table, where vmn-exp is ahead, where W&B is the right tool (hosted service, HTTP logging, media types, Hyperband, LLM traces, per-project permissions), each labelled planned, not planned or not offered by design as F14 records, an API mapping table (wandb.init/log/alert/define_metric/watch/sweep/WANDB_MODE to the documented vmn-exp equivalents), a Sources section with an as-of date, and a plain 'no importer yet' line. No performance comparison (PRODUCT.md:51). Link it from docs/vmn-exp/README.md and CLAUDE.md's Docs Layout (approved). The wheel picks it up through the docs/*.md package-data glob, which test_installation.py:132-137 already checks.

**Tests first.**

- packages/vmn-exp/tests/test_docs_links.py::test_the_docs_index_links_every_vmn_exp_doc (from F4; red as soon as vmn-vs-wandb.md exists unlinked)
- test_docs_links.py::test_the_vmn_exp_docs_have_no_broken_relative_links (from F4; covers the new page's links)

**Files.** `docs/vmn-exp/vmn-vs-wandb.md`, `docs/vmn-exp/README.md`, `CLAUDE.md` (no new test file; F4's two real-file tests go red, then green)

**Risk.** W&B claims must be sourced and dated by the implementer; nothing about W&B was verified in this pass.

**Evidence.** `packages/vmn-exp/src/vmn_exp/importers/ (cli.py, mlflow_client.py, mlflow_filestore.py, mlflow_features.py, import_records.py, commit_changes.py, refresh_features.py: no wandb module)`; `docs/vmn-exp/sweeps.md:3-4`; `docs/vmn-exp/sdk.md:394`; `docs/plans/README.md:1`; `docs/plans/20-flows-beat-wandb-mlflow.md:9-12`; `packages/vmn-exp/tests/test_installation.py:132-137`

<a id="f5"></a>
### F5. Split the HTTP API out of ui.md into ui-api.md; a table of contents in both

P2 · M · depends on F4

**Problem.** ui.md is 1,967 lines with no TOC (experiments.md has one at :20-34). Lines 1-836 are the operator and user guide (22 H2/H3 sections: install, flags, workspaces, deployment, the index, diagnostics, the boards, compare, keyboard). Lines 837-1967 are the HTTP API reference: `## API` with 24 H3 sections. A reader looking for a flag scrolls past nothing useful; a reader looking for a route has to know it is in the second half. ui.md:450 is one bullet of 789 characters (and :453 is 2,609).

**Approach.**

Docs plus two approved test-path edits. No wording changes inside the moved text.

1. **Move.** New docs/vmn-exp/ui-api.md with the title `# vmn-exp ui: HTTP API`, one intro sentence linking back to ui.md, then everything from `## API` (ui.md:837) to the end of the file. Headings keep their text and their level (`## API`, then the 24 `###`), so every anchor slug is unchanged and only the file name in a link changes.
2. **Stub.** ui.md keeps a short `## API` section: two sentences and a link to ui-api.md. An old bookmark to `ui.md#api` still lands on something.
3. **Tests that read the moved section** (edits approved by the owner):
   - packages/vmn-exp/tests/test_docs_similar_statements.py:49: `_section("docs/vmn-exp/ui.md", "### Similar runs")` becomes `_section("docs/vmn-exp/ui-api.md", "### Similar runs")`.
   - the same change at test_docs_similar_statements.py:116.
   No other test reads ui.md by name. test_docs_import_mlflow_examples.py:25 and test_installation.py:135 glob `docs/vmn-exp/*.md` and pick the new file up by themselves; the wheel ships it through the `docs/*.md` package-data glob (packages/vmn-exp/pyproject.toml:48).
4. **Cross-doc links into moved anchors** (13; each `ui.md#x` becomes `ui-api.md#x`):
   - docs/vmn-exp/server.md:239 `#similar-runs`, :524 `#status-counts-and-rollup`, :533 `#baseline-compare`
   - docs/vmn-exp/experiments.md:443 `#status-counts-and-rollup`, :1224 `#similar-runs`
   - docs/vmn-exp/sdk.md:307 `#custom-x-axis`, :738 `#outer-runs-scope-and-search`, :1127 `#filtering-with-a-query`, :1172 `#experiment-status-fields`
   - docs/vmn-exp/reports.md:104 `#pivot-heatmap`
   - docs/vmn-exp/models.md:279 `#model-registry-api`
   - docs/vmn-exp/ai-fleet-tracking.md:153 `#api`
   - docs/plans/18-similar-runs.md:13 `#similar-runs`
5. **Cross-doc links that stay on ui.md** (12; listed so nobody repoints them): server.md:98, :347, :372, :381, :517, :522, :543; experiments.md:471, :1444, :1497, :2066; docs/plans/34-fgm-attempts-baseline-lost.md:38.
   Three whole-file links carry no anchor but say in their text that the HTTP API is in ui.md; each gains a second link to ui-api.md: docs/vmn-exp/architecture.md:394 ('See ui.md for the flags and the HTTP API'), docs/vmn-exp/experiments.md:16 ('the web UI and HTTP API (ui.md)') and experiments.md:2116 ('HTTP API are in ui.md').
6. **In-file links that now cross the cut.**
   - guide to API (become `ui-api.md#x`): ui.md:458, :557 and :561 `#baseline-compare`; :492 `#outer-runs-scope-and-search`; :561 `#pivot-heatmap`; :605 and :692 `#experiment-status-fields`; :694 and :709 `#facets`.
   - API to guide (become `ui.md#x` in the new file): ui.md:846 `#workspaces`; :876 `#actions`; :914, :1196 and :1556 `#outer-runs-and-the-outer-runs-page`; :966 `#the-tree`; :1186 `#saved-and-team-views`.
   F4's checker finds any that this list misses: a moved heading leaves a dangling `#anchor` in the file it left.
7. **Index lines.**
   - docs/vmn-exp/README.md:39: the ui.md row becomes '`vmn-exp ui`: deployment, the index, the boards'; a new row for ui-api.md says 'the HTTP API'.
   - CLAUDE.md:213 (the vmn-exp topic table): the row splits into '`vmn-exp ui`, boards, outer runs, pivots, baselines | `ui.md`' and 'HTTP API | `ui-api.md`'.
   - CLAUDE.md:244 (Docs Layout): '`ui.md`: `vmn-exp ui` deployment and the dashboard. `ui-api.md`: the HTTP API.'
   The CLAUDE.md docs-layout edits are approved by the owner.
8. **Mentions that do not change** (they name guide sections, which stay): packages/vmn-exp/webui/src/shell/contracts.ts:119 (`DOCS_URL` to ui.md), ui/gil_hint.py:17 ('Large stores'), ui/diag/__init__.py:4 (diagnostic dumps), cli/skill.py:332 ('Diagnostic dumps, Store upkeep'). So docs/vmn-exp/agent-skill.md needs no regeneration.
9. **TOC.** ui.md gets a TOC under its title listing every H2. ui-api.md gets one listing every H3 under `## API`. Break ui.md:450 into sub-bullets without changing the wording (keeping F4's corrected link). A pure helper missing_toc_entries(text, level) in doc_links.py reports headings of that level with no TOC link.

**Tests first.**

- packages/vmn-exp/tests/test_docs_links.py::test_a_toc_missing_a_heading_is_reported (in-memory text)
- test_docs_links.py::test_ui_md_lists_every_h2_in_its_toc (real file; red today)
- test_docs_links.py::test_ui_api_md_lists_every_api_section_in_its_toc (real file; red today, file missing)
- packages/vmn-exp/tests/test_docs_similar_statements.py: the two path edits above, made before the move, so both tests are red until ui-api.md holds `### Similar runs`
- test_docs_links.py::test_the_vmn_exp_docs_have_no_broken_relative_links and ::test_the_docs_index_links_every_vmn_exp_doc (both from F4) go red during the move and green once steps 4, 6 and 7 are done

**Files.** `docs/vmn-exp/ui.md`, `docs/vmn-exp/ui-api.md` (new), `docs/vmn-exp/README.md`, `docs/vmn-exp/server.md`, `docs/vmn-exp/experiments.md`, `docs/vmn-exp/sdk.md`, `docs/vmn-exp/reports.md`, `docs/vmn-exp/models.md`, `docs/vmn-exp/ai-fleet-tracking.md`, `docs/vmn-exp/architecture.md`, `docs/plans/18-similar-runs.md`, `CLAUDE.md`, `packages/vmn-exp/tests/test_docs_similar_statements.py`, `packages/vmn-exp/tests/doc_links.py`, `packages/vmn-exp/tests/test_docs_links.py`

**Risk.** External bookmarks to `ui.md#<api section>` land at the top of ui.md; the `## API` stub covers only `#api`. Line numbers above are HEAD's (`59becdd5`) and move with any earlier ui.md edit, so do the split in one commit and re-grep `ui\.md#` first. Plan 42 edits the API text: E13 (the endpoint table and its new test_docs_ui_endpoints.py) is ordered after F5 and reads ui-api.md through one file constant; any other E item whose Files line names `docs/vmn-exp/ui.md` for API text targets ui-api.md once F5 has landed. docs/plans/ is outside F4's scope except README.md, so the 18-similar-runs.md link is fixed by hand.

**Owner decision (2026-11-11).** Split the HTTP API into its own file.

**Evidence.** `docs/vmn-exp/ui.md:450`; `docs/vmn-exp/ui.md:837`; `docs/vmn-exp/ui.md:1857`; `docs/vmn-exp/ui.md:1961`; `docs/vmn-exp/experiments.md:20-34`; `packages/vmn-exp/tests/test_docs_similar_statements.py:30-45`; `packages/vmn-exp/tests/test_docs_similar_statements.py:49`; `packages/vmn-exp/tests/test_docs_similar_statements.py:116`; `packages/vmn-exp/tests/test_docs_import_mlflow_examples.py:25`; `packages/vmn-exp/tests/test_installation.py:132-137`; `packages/vmn-exp/pyproject.toml:48`; `docs/vmn-exp/README.md:39`; `docs/vmn-exp/architecture.md:394`; `docs/vmn-exp/experiments.md:16`; `docs/vmn-exp/experiments.md:2116`; `CLAUDE.md:213`; `CLAUDE.md:244`; `packages/vmn-exp/webui/src/shell/contracts.ts:119`; `packages/vmn-exp/src/vmn_exp/ui/gil_hint.py:17`; `packages/vmn-exp/src/vmn_exp/cli/skill.py:332`; `docs/plans/42-vmn-exp-server-security-api.md (E13)`

<a id="f6"></a>
### F6. experiments.md: use the vmn-exp command names; one home for the stuck formula and for install

P3 · S · depends on F4

**Problem.** experiments.md writes bare `exp run`/`exp list`/`exp show`/`exp add`/`exp create`/`exp diff` in 15 lines including a heading and its TOC entry (:22, :88, :125, :127, :191, :209, :255, :330, :381, :400, :419, :478, :1552); the alias is real (:509-511) but every other doc says `vmn-exp run`. The stuck formula is spelled out in five vmn-exp docs (experiments.md:262, client-guide.md:468, sdk.md:950, ai-fleet-tracking.md:30, vmn-vs-mlflow.md:102) plus CLAUDE.md:219. Full install blocks repeat in README.md:9, client-guide.md:45-53, ui.md:11, sdk.md:1481, packaging.md:11-13 and both package READMEs.

**Approach.**

Docs only. (1) Replace bare `exp <action>` with `vmn-exp <action>` in experiments.md, except the alias paragraph (:509-511) and `runner: exp run` (:215), which shows a stored value. The heading at :125 changes its anchor: update the TOC entry at :22; F4 catches any other inbound link. (2) Stuck rule: experiments.md 'Run status' stays the one place with the formula; the other four docs keep a clause ('past its stuck window') and a link. CLAUDE.md:219 stays, since it is agent context. (3) Install: client-guide.md is canonical for users and packaging.md for the package split; ui.md and sdk.md keep one line naming their extra and link to it. The package READMEs and docs/vmn-exp/README.md keep theirs (PyPI and the index render standalone). One-line `pip install "vmn-exp[parquet]"` style hints elsewhere stay.

**Tests first.**

- packages/vmn-exp/tests/test_docs_positioning.py::test_bare_exp_commands_are_reported (pure bare_exp_commands(text) on in-memory text; allows 'vmn-exp exp list', 'vmn exp list' and 'runner: exp run')
- test_docs_positioning.py::test_experiments_md_uses_vmn_exp_command_names (real file; red today)
- test_docs_positioning.py::test_the_stuck_formula_is_spelled_out_only_in_experiments_md (regex 'max\(3 .{1,40}60' over docs/vmn-exp/*.md; red today with four other files)

**Files.** `docs/vmn-exp/experiments.md`, `docs/vmn-exp/client-guide.md`, `docs/vmn-exp/sdk.md`, `docs/vmn-exp/ai-fleet-tracking.md`, `docs/vmn-exp/vmn-vs-mlflow.md`, `docs/vmn-exp/ui.md`, `packages/vmn-exp/tests/test_docs_positioning.py`

**Risk.** The anchor #with-a-command-exp-run-and-the-metrics-file changes (F4 covers internal links). test_docs_similar_statements.py reads '### `similar`' from experiments.md; that heading is not renamed. No install test is added: a string test there would only restate the edit.

**Evidence.** `docs/vmn-exp/experiments.md:22`; `docs/vmn-exp/experiments.md:125`; `docs/vmn-exp/experiments.md:215`; `docs/vmn-exp/experiments.md:509-511`; `docs/vmn-exp/experiments.md:1552`; `docs/vmn-exp/experiments.md:262`; `docs/vmn-exp/client-guide.md:468`; `docs/vmn-exp/sdk.md:950`; `docs/vmn-exp/ai-fleet-tracking.md:30`; `docs/vmn-exp/vmn-vs-mlflow.md:102`; `docs/vmn-exp/client-guide.md:45-53`; `docs/vmn-exp/sdk.md:1481`; `docs/vmn-exp/ui.md:11`

<a id="f8"></a>
### F8. Bring docs/plans/README.md and the plan Status lines up to date, with a consistency test

P2 · M · depends on F4

**Problem.** The plans index misleads anyone reading it as a roadmap, and it is staler than reported. Rows that say missing or design for shipped work: 1 (rerun: experiments.md:1030), 4 (first/mean summaries exist: core/metric_summary.py:34), 4b and 7 (auto-step, disabled mode: sdk.md:789-797), 6 (use_model/use_dataset: sdk/run.py:693-699), 8 (torch watch(): integrations/torch_watch.py:144), 9 (offline push: experiments.md:1992), 10 (docs/snapshots.md exists), 11-14 (server.md, reports.md, LAYOUT = 2 in store_marker.py:20). Row and file disagree: 17 (row 'proposal', file 'done 2026-10-10'), 19 (row 'done', file 'proposal'), 20 (row 'done', file 'proposal'). Plan files 11-14 still say 'not started'. The intro still says 'Status of the 9 candidate features'. 28-measurements.md has no row or link in the index. The index stops at row 36: plans 37-44 (this review) have no rows.

**Approach.**

Docs plus one test. For each stale row the implementer confirms in code what shipped (plans 6, 12 and 13 need a section-by-section check; this pass confirmed only that the named features exist) and sets the row to one of a fixed vocabulary: proposal, in progress, done, done except <what>, evaluation. Each plan file's own Status line gets the same word and a date; files without a Status line (01, 04, 06, 08, 09, 10, 22-27 as applicable) gain one. Rewrite the intro line, link 28-measurements.md from row 28, and add rows 37-44 (the row for plan 43 names F14 as the roadmap decision record). Pure helper plans_index_problems(index_text, {filename: text}) reports: plan files not linked from the index, and rows whose first status word differs from the file's Status word. Missing link targets are already F4's job (docs/plans/README.md is in its scope).

**Tests first.**

- packages/vmn-exp/tests/test_plans_index.py::test_a_plan_file_the_index_does_not_link_is_reported (in-memory)
- test_plans_index.py::test_a_done_row_over_a_proposal_status_line_is_reported (in-memory; the row 19/20 case)
- test_plans_index.py::test_a_proposal_row_over_a_done_status_line_is_reported (in-memory; the row 17 case)
- test_plans_index.py::test_the_plans_index_agrees_with_the_plan_files (real docs/plans; red today)

**Files.** `docs/plans/README.md`, `docs/plans/*.md (Status lines only)`, `packages/vmn-exp/tests/test_plans_index.py`

**Risk.** Marking something done that is only partly built; contained by 'done except <section>' wherever the implementer cannot find the code for a plan section. Plan 35 is core vmn (still proposed; row and file agree) but its row lives in the same index, so the test sits in the exp suite and reads only markdown.

**Evidence.** `docs/plans/README.md:3`; `docs/plans/README.md:8-22 (rows 1-14)`; `docs/plans/17-detached-head-and-goto.md:3`; `docs/plans/19-vmn-native-shell.md:14`; `docs/plans/20-flows-beat-wandb-mlflow.md:12`; `docs/plans/11-central-server.md:3`; `docs/plans/12-columnar-metrics.md:3`; `docs/plans/13-reports-comments.md:3`; `docs/plans/14-store-layout.md:3`; `packages/vmn-exp-sdk/src/vmn_exp/core/metric_summary.py:34`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:693-699`; `packages/vmn-exp-sdk/src/vmn_exp/integrations/torch_watch.py:144`; `packages/vmn-exp-sdk/src/vmn_exp/storage/store_marker.py:20`; `docs/vmn-exp/sdk.md:789-797`; `docs/vmn-exp/experiments.md:1030`; `docs/vmn-exp/experiments.md:1992`

<a id="f9"></a>
### F9. Patch-only release rules: upgrading.md, the removal rule for deprecations, and a format-version ratchet

P1 · M

**Problem.** All 38 releases from 0.1.0 (2026-09-28) to 0.1.37 (2026-11-10) are patch bumps: release_exp.sh hardcodes mode=patch (:19), minor only for the first release. That includes index bumps (records 18 -> 19 and derived 19 -> 21 at 0.1.35, records 20 at 0.1.36) and the 40-minute 0.1.35 upgrade plan 33 was written for. server.md:142-178 explains the upgrade mechanism, but nothing says which release changes which format, what an upgrade costs, or which release changed a behaviour. The owner decided releases stay patch-only, so a version number can never signal a breaking change. The signal has to be a document and a test: plans 38-42 change behaviour in at least eleven places, and plan 41 D5, D7, D9 and D11 deprecate SDK behaviour 'then remove' with no unit to count the distance in.

**Approach.**

New docs/vmn-exp/upgrading.md holds the rules and three tables. Every other plan refers to it as "the removal rule in plan 43 F9" and "an upgrading.md row".

*Rules (the policy section of upgrading.md).*

1. **Every release is a 0.1.x patch.** release_exp.sh is unchanged. No release carries meaning in its number; upgrading.md and the changelog carry it.
2. **A behaviour change lands with its row.** A behaviour change is anything a user or operator could have relied on that now acts differently: a documented CLI flag, output or exit code; an HTTP route or response field; an SDK call, default or exception; a default view; an environment variable; a supported interpreter. The change that makes it adds a row to the *Behaviour changes* table in the same commit series, with the version it will ship in (the next release: the pyproject version's patch plus one), and at least one of its commits is marked with `!` (`fix(sdk)!: ...`) so F10's changelog lists it under 'Behaviour changes'.
3. **The removal rule for deprecations.** A deprecated call, flag, route or name keeps working and warns (DeprecationWarning from the SDK; one stderr line from the CLI), and gets a row in the *Deprecations* table when the warning ships. It may be removed no sooner than **10 releases and 30 days** after the release that first carried the warning, both conditions together. *Both numbers are proposed, owner to confirm.* Because every release is a patch of 0.1, the release distance is the difference of the patch numbers.
   Why these numbers: the 38 releases so far fall on 16 days in 43, with 12 on 2026-10-22 alone, a longest gap of 11 days (10-03 to 10-14), and 33 releases in the 30 days to 2026-11-10. A count alone can pass in a day, so the 30 days is the term that protects a job image rebuilt monthly; at today's pace it is the one that binds. The 10 releases matter only if releases slow below one every three days: then the window stretches, so a warning is never removed after sitting in only two or three installable versions.
4. **What takes effect at once.** A change the owner decided is immediate (a security fix, a guard that rejects input which was silently wrong) needs only a Behaviour row, not a deprecation window. The decided ones are listed below.
5. **Format changes.**
   - *In-place index bump* (RECORDS_VERSION or DERIVED_VERSION, upgraded in place as server.md:151-178 describes): a row in the *Formats* table in the same change. This is what 0.1.35 and 0.1.36 were.
   - *Store layout (LAYOUT), record format (RECORD_FORMAT_VERSION), or an index upgrade that reloads from storage* (the new-generation-file path, server.md:161-166): the row also names an earlier release in its 'Announced in' cell, meaning upgrading.md already carried a 'planned' note for it in a release that shipped before; states the upgrade's cost (time per 100k runs, free disk, what stops serving meanwhile) and the operator's steps; and its commit is marked `!`. So the notice is always at least one release old before the change ships.
   - *Order of upgrade*, stated once in the policy: the server and CLI first, job images after. A reader reads every older record of its layout and format (F11); a newer record is skipped with a warning that says 'upgrade vmn-exp' (record_format.py:38-60) and an unknown layout is refused (store_marker.py:248-251).
   - *A record-format bump additionally waits out the removal rule*: writers may start writing format N+1 only 10 releases and 30 days after the release whose readers accept N+1, so a server upgraded inside the window never skips records. Today one constant serves writer and reader (record_format.py:17), so the first such bump has to split 'highest format read' from 'format written'. That is work for the plan that proposes the bump, not for F9.
6. **1.0 is not promised.** Nothing here is a stability guarantee beyond these rules.

*Tables (newest first).*

- **Behaviour changes**: Version | Date | What changed | What to do | Plan item.
- **Deprecations**: What | Warned in | Warned on | Removed in | Removed on (the last two empty until removal).
- **Formats**: Version | Store layout | Record format | Index records | Index derived | Upgrade (in place / reload) | Cost and operator steps | Announced in.
  Backfill only what the tags prove: the baseline at 0.1.30 (records 18, derived 19), 0.1.35 (19 / 21) and 0.1.36 (20 / 21), all in place, layout 2 and record format 2 throughout; one sentence says earlier releases rebuilt the cache on every index change.

*Rows the decided items of plans 38-42 owe.* Each lands with the item, not with F9; F9 ships the tables and the first Formats rows.

| Item | Behaviour row |
|---|---|
| 38 A5 / A12 | A script launched by `vmn-exp run`, a rerun or a sweep trial that calls `start_run()` records into the wrapper's run: one run where there were two. Opt out with `--no-adopt` or `VMN_EXP_ADOPT=0`. |
| 38 A6 | An app with no outer runs opens on the runs board with metric columns, not on the Outer runs board. |
| 39 B1 | `vmn-exp --version` prints vmn-exp's own version only. |
| 39 B5b | A flag the action does not own exits 2 instead of being ignored. |
| 40 C7 | Finalization budget: 25 s under SIGTERM, 60 s for `finish()` and atexit, one environment variable. |
| 40 C8 | `sys.exit(N)` with a run left open records the run as failed with exit code N. |
| 41 D8 | `define_metric` raises on an unknown keyword at once (no deprecation window). |
| 42 E1 | UI job commands are built as `--flag=value` for every option. |
| 42 E2 | OIDC refuses a non-https issuer or endpoint and does not follow redirects. |
| 42 E8 | The Host and cross-site guards also apply to `/metrics` and `/auth`. |
| 43 F12 | Both packages require Python >=3.10; pip on 3.8 or 3.9 keeps resolving to the last release that supported them. |

Plan 41 D5, D7, D9 and D11 are 'warn, then remove': each gets a Deprecations row when its warning ships and is removed per rule 3. Plan 41 D3 (modules moved from the SDK wheel to vmn-exp) gets a Behaviour row for any import path that moves.

The table is the set the owner's answers changed, not every row. Other items in plans 38-42 name their own row in their own text (at this edit: 38 A1, A3, A10; 39 B2, B3, B4c, B5d, B7, B8, B9d; 40 C1, C2, C5, C6, C9, C15, C16; 42 E3, E5a, E6, E9) and add it the same way, under rule 2.

*Ratchet.* A test-support module packages/vmn-exp/tests/upgrading_table.py with three pure functions over text and plain values:
- parse_tables(text) returns the rows of the three tables;
- format_table_problems(rows, constants) reports: the newest Formats row's four numbers differing from the code's LAYOUT, RECORD_FORMAT_VERSION, RECORDS_VERSION and DERIVED_VERSION; a row whose layout or record format differs from the row below it, or whose Upgrade cell is 'reload', with an empty cost cell or with an 'Announced in' that is empty or not an earlier version;
- deprecation_problems(rows, min_releases, min_days) reports a row with 'Removed in' filled whose patch distance from 'Warned in' is under min_releases or whose 'Removed on' is under min_days after 'Warned on'.
The two numbers live once, as constants in upgrading_table.py, next to a comment naming this item.

Also: packaging.md:172-174 says the release is always a patch and links upgrading.md; link upgrading.md from docs/vmn-exp/README.md, from server.md's Upgrades section (:142) and from CLAUDE.md's Docs Layout (approved).

**Tests first.**

- packages/vmn-exp/tests/test_upgrading_md.py::test_a_newest_format_row_behind_the_code_constants_is_reported (in-memory rows)
- test_upgrading_md.py::test_an_in_place_index_bump_needs_only_its_row (in-memory rows)
- test_upgrading_md.py::test_a_layout_or_record_format_change_without_an_earlier_announcement_is_reported (in-memory rows)
- test_upgrading_md.py::test_a_reload_upgrade_without_a_cost_is_reported (in-memory rows)
- test_upgrading_md.py::test_a_removal_under_ten_releases_is_reported (in-memory rows: warned 0.1.40, removed 0.1.45, 60 days apart)
- test_upgrading_md.py::test_a_removal_under_thirty_days_is_reported (in-memory rows: warned 0.1.40, removed 0.1.60, 5 days apart)
- test_upgrading_md.py::test_a_removal_past_both_distances_is_accepted
- test_upgrading_md.py::test_upgrading_md_documents_the_current_format_versions (real file against the imported constants; red today, file missing)
- test_upgrading_md.py::test_upgrading_md_breaks_no_removal_rule (real file)

**Files.** `docs/vmn-exp/upgrading.md` (new), `docs/vmn-exp/README.md`, `docs/vmn-exp/server.md`, `docs/packaging.md`, `CLAUDE.md`, `packages/vmn-exp/tests/upgrading_table.py` (new), `packages/vmn-exp/tests/test_upgrading_md.py` (new)

**Risk.** The ratchet makes every future format bump need a docs row in the same change; that is the intent. Rule 2 is not machine-checked: no test can tell that a commit changed behaviour, so a missing Behaviour row is caught only in review and by the plan items naming their row. 'Removed on' is typed by hand; the test checks the arithmetic, not the calendar. The two numbers are proposals; if the owner changes them, two constants and one sentence change. The record-format read-before-write rule cannot be met by today's single constant and is recorded as a condition on a future bump. release_exp.sh, its test and `.vmn/vmn_exp/conf.yml` are untouched.

**Owner decision (2026-11-11).** Releases stay 0.1.x patch releases, with no batched minor release. Every behaviour change gets an upgrading.md row and a changelog entry. Still open for the owner: confirm the removal distance (proposed: 10 releases and 30 days).

**Evidence.** `release_exp.sh:18-30`; `git for-each-ref refs/tags/vmn_exp_* (39 tags, creator dates 2026-09-28 to 2026-11-10)`; `packages/vmn-exp-sdk/src/vmn_exp/core/index_store_schema.py:61-63`; `packages/vmn-exp-sdk/src/vmn_exp/core/record_format.py:17`; `packages/vmn-exp-sdk/src/vmn_exp/core/record_format.py:38-60`; `packages/vmn-exp-sdk/src/vmn_exp/storage/store_marker.py:20`; `packages/vmn-exp-sdk/src/vmn_exp/storage/store_marker.py:248-251`; `docs/vmn-exp/server.md:142-178`; `packages/vmn-exp/tests/test_release_exp_script.py:41-49`; `docs/packaging.md:172-174`; `docs/plans/37-vmn-exp-review-fixes.md (Decisions; What the answers change, point 2)`

<a id="f10"></a>
### F10. Generated CHANGELOG.md for vmn-exp: git-cliff scoped to the two exp packages, regenerated after each upload

P1 · M · depends on F9

**Problem.** vmn-exp has no changelog (no CHANGELOG file, no cliff.toml). 1,758 commits went into the 38 releases, 1,444 of them touching packages/vmn-exp or packages/vmn-exp-sdk. vmn's own changelog.path feature does not fit: it groups every commit since the app's tag with no path filter (publisher.py:582-584), so core vmn commits would be mixed in, and it needs conventional_commits, which changes how the release mode is resolved. Under patch-only releases (F9) the changelog is one of the two places a behaviour change is announced.

**Approach.**

Make the changelog a pure function of history. Add packages/vmn-exp/cliff.toml: tag_pattern for vmn_exp_ tags, the 0.0.0 init tag skipped; feat / fix / perf kept; a commit with `!` or a BREAKING CHANGE footer grouped first under 'Behaviour changes' (F9 rule 2); test / refactor / docs / chore / style and 'Stamped version' commits skipped; a header line points at upgrading.md. Add a Makefile target `_changelog` (vmn_exp only) that runs `git-cliff --config packages/vmn-exp/cliff.toml --include-path 'packages/vmn-exp/**' --include-path 'packages/vmn-exp-sdk/**' -o packages/vmn-exp/CHANGELOG.md`, commits it as `docs(exp): changelog` when it changed, and pushes. release_exp.sh calls `make _changelog NAME=vmn_exp` after `make upload`. Because the whole file is rebuilt from tags, the backfill of 0.1.0 to 0.1.37 is the same command, a rerun is idempotent, and the next version never has to be predicted. The file is never hand-edited; operator notes live in upgrading.md (F9). 1,319 of the 1,758 commit subjects already follow the convention, so no history rewrite. The wheel does not ship the file; F12 adds the Changelog URL. The CI release lane (make _<mode>, _build, upload) gains the step as a follow-up; note it in ci/README.md.

**Tests first.**

- packages/vmn-exp/tests/test_release_exp_script.py::test_the_changelog_is_regenerated_after_the_upload (the existing stub PATH, no real git: calls end with 'make upload NAME=vmn_exp', 'make _changelog NAME=vmn_exp'; red today).
- test_release_exp_script.py::test_releases_only_the_exp_packages_with_patch: its exact call list (:41-49) gains 'make _changelog NAME=vmn_exp' as the last entry. Approved test edit.
- packages/vmn-exp/tests/test_workspace.py::test_the_exp_changelog_config_reads_only_vmn_exp_tags_and_user_facing_commits (toml.load of cliff.toml: tag pattern; feat/fix/perf kept; test/refactor/docs skipped; a 'Behaviour changes' group for `!`)
- packages/vmn-exp/tests/test_exp_changelog.py::test_only_commits_under_the_exp_packages_between_exp_tags_are_listed (thin real-IO test, after the two unit tests above: a temp git repo with two vmn_exp_ tags, one vmn_ tag, commits under packages/vmn-exp, packages/vmn and docs, one of them `fix(sdk)!:`; runs the venv's git-cliff with the real config and the include paths; asserts the core and docs commits are absent, the sections are per vmn_exp tag, and the `!` commit is under 'Behaviour changes')

**Files.** `packages/vmn-exp/cliff.toml`, `packages/vmn-exp/CHANGELOG.md`, `Makefile`, `release_exp.sh`, `packages/vmn-exp/tests/test_release_exp_script.py`, `packages/vmn-exp/tests/test_workspace.py`, `packages/vmn-exp/tests/test_exp_changelog.py`, `docs/packaging.md`, `ci/README.md`

**Risk.** The changelog commit lands after the tag, so a tag's tree holds the changelog up to the previous release; the Changelog URL points at master, which is current. If the push fails the release is already out and rerunning `make _changelog` repairs it. The commit is 'docs(exp)', so it never appears in the next changelog. How git-cliff orders and names these tags, and whether the pinned git-cliff (>=2.5,<3) accepts every config key, are not verified; the real-git test is there to settle that. The changelog can only show a behaviour change whose commit carries `!`; F9 rule 2 asks for it and nothing enforces it. The owner answered the placement only; which commit types are listed (feat / fix / perf in, refactor / docs / test out) is this item's choice and is one list in cliff.toml.

**Owner decision (2026-11-11).** The changelog is regenerated after the upload; it does not have to be inside the release tag.

**Evidence.** `packages/vmn/src/version_stamp/stamping/publisher.py:569-585`; `packages/vmn/pyproject.toml:24`; `tests/test_requirements.txt:14`; `release_exp.sh:18-30`; `Makefile:24-33`; `build_dist.sh:25-45`; `packages/vmn-exp/tests/test_release_exp_script.py:22-49`; `ci/pipeline.py:181-232`; `git rev-list --count vmn_exp_0.0.0..vmn_exp_0.1.37 [-- packages/vmn-exp packages/vmn-exp-sdk]`

<a id="f11"></a>
### F11. State and test the SDK/server compatibility contract; keep the == pin; one golden record per format

P2 · M · depends on F9

**Problem.** The finding asks for a relaxed vmn-exp-sdk pin. That is unsafe: vmn-exp imports many vmn_exp.core/storage/sdk/registry/_base modules from the SDK distribution, some by private name, and both distributions share one PEP 420 namespace, so a mismatched pair in one environment can fail at import. The pin constrains only an environment where vmn-exp itself is installed. What is missing is the written contract between a job's SDK version and the server/CLI version across the store. The code has one: an unknown layout is refused (store_marker.py:248-251), a newer record format is skipped with an 'upgrade vmn-exp' warning (record_format.py:38-60), and those refusals are already tested (test_record_format_read.py:56, :84, :109). packaging.md:160-162 only says the shared version keeps 'the dashboard and the job writer' agreeing, and no test pins an older writer's record as readable by today's reader.

**Approach.**

(1) docs/packaging.md gains a 'Compatibility' section, linked from upgrading.md. It says: vmn-exp and vmn-exp-sdk in one environment are always the same version (the pin, and why). Across machines the contract is the store, and the promise is one sentence: **a server or CLI reads the records written by any older SDK of the same store layout and record format.** A record of a newer format is skipped with a warning; an unknown layout is refused. So upgrade the server/CLI first and job images at leisure. A format change follows F9 rule 5. Nothing is promised in the other direction beyond 'entries of an unknown type add nothing of their own'.
(2) One golden record per record format. Today that is one: packages/vmn-exp/tests/golden/record_format_2/, a small frozen record as 0.1.37 writes it (metadata.yml with format_version 2, a handful of JSONL log lines of each entry type, run_state.yml), loaded into an EmptyStorage subclass (tests/empty_storage.py) and folded; assert metrics, params, tags and derived status. Format 1 needs none: it is refused with the migrate hint, which test_record_format_read.py:70 already pins. A later format bump adds golden/record_format_<N>/ and keeps every older golden green.
(3) One fold test for an unknown entry type. Reading fold.py:233-267: `_apply` dispatches on the known types and falls through for anything else, but the params an entry carries are folded whatever its type (:255-259). So the test asserts exactly that: an unknown-type entry with no params changes nothing in the fold. The doc sentence says the same and no more.
(4) Add the reason to the comment on test_workspace's pin test (:32-35); no pyproject change.

**Tests first.**

- packages/vmn-exp/tests/test_record_compat.py::test_a_format_2_record_written_by_0_1_37_folds_to_the_same_metrics_params_and_status (golden files through an EmptyStorage subclass; no real store)
- test_record_compat.py::test_a_log_line_of_an_unknown_type_adds_nothing_to_the_fold (in-memory entries)
- test_record_compat.py::test_every_record_format_this_reader_accepts_has_a_golden_record (lists golden/record_format_*/ against RECORD_FORMAT_VERSION; red until the directory exists, and red again at the next bump until its golden is added)
- packages/vmn-exp/tests/test_docs_positioning.py::test_packaging_md_compatibility_names_the_current_layout_and_record_format (the section carries the numbers of store_marker.LAYOUT and RECORD_FORMAT_VERSION)

**Files.** `docs/packaging.md`, `docs/vmn-exp/upgrading.md`, `packages/vmn-exp/tests/test_record_compat.py`, `packages/vmn-exp/tests/golden/record_format_2/`, `packages/vmn-exp/tests/test_workspace.py`, `packages/vmn-exp/tests/test_docs_positioning.py`

**Risk.** No packaging change, so no install risk. The first two tests pin existing behaviour and may be green on first run; the implementer must show each fails when the behaviour is broken (mutate the fold locally) before trusting it. If the unknown-type test is red, that is a finding to report, and the doc sentence changes instead of the code. The golden is written by hand to match what 0.1.37 writes; build it by running 0.1.37's SDK once against a temp store and copying the files, not from memory of the format.

**Owner decision (2026-11-11).** Keep the `==` pin. Promise that a server reads records from any older SDK of the same layout and record format, backed by one golden record per format.

**Evidence.** `packages/vmn-exp/pyproject.toml:15-19`; `packages/vmn-exp/tests/test_workspace.py:32-35`; `build_dist.sh:34-38`; `.vmn/vmn_exp/conf.yml:14-17`; `packages/vmn-exp-sdk/src/vmn_exp/core/record_format.py:17`; `packages/vmn-exp-sdk/src/vmn_exp/core/record_format.py:38-60`; `packages/vmn-exp-sdk/src/vmn_exp/storage/store_marker.py:248-251`; `packages/vmn-exp/tests/test_record_format_read.py:56`; `packages/vmn-exp/tests/test_record_format_read.py:70`; `docs/packaging.md:160-162`; `packages/vmn-exp-sdk/src/vmn_exp/core/fold.py:233-267`; `packages/vmn-exp/tests/empty_storage.py`; `packages/vmn-exp/tests/golden/ (holds run_detail.json today)`

<a id="f12"></a>
### F12. Both exp packages require Python >=3.10; pyproject metadata, bounded extras, and the stale PyPI section of packaging.md

P2 · M · depends on F9, F10

**Problem.** requires-python is >=3.8 on both exp packages (pyproject.toml:13 in each), and nothing tests it: CI runs one Python (3.12 by default, ci/README.md:282), and tests/run_install_matrix.sh covers only `pip install vmn`. Statically vmn-exp[ui] cannot import on 3.8 (ui/shell_meta.py:25 uses functools.cache), the Docker test requirements install fastapi and uvicorn only on >=3.9 (tests/test_requirements_docker.txt:10-13), and ui.md:246 tells operators to run 3.15t. Both pyprojects also have no classifiers, no keywords and only a Homepage URL (vmn-exp :40-41, sdk :30-31); unbounded extras: mlflow-skinny, pyarrow (vmn-exp :31, :33), boto3, pandas, azure-identity (sdk :22-26). docs/packaging.md:188-193 still says the exp packages are only 0.0.1 placeholders on PyPI, although 38 releases were tagged and release_exp.sh uploads each one.

**Approach.**

1. **Check the interpreters real jobs use, before anything else.** The floor drops 3.8 and 3.9 job images in a patch release, so know who is on them first.
   - What the repo can show: nothing about client images. No doc states a minimum Python (no match in docs/vmn-exp, docs/packaging.md or the package READMEs); the Dockerfile at the repo root is core vmn's (`ARG PYTHON_VERSION=3`); CI runs 3.12; the install matrix (3.8 to 3.12) installs only vmn; the load-harness table in ui.md:263-269 shows the UI was once run on 3.9.
   - What each store can show: every run records its interpreter. `env.python` is in the run's metadata.yml summary (core/env.py:240; experiments.md:624-627) and is a query field (`env.<key>`, experiments.md:632). On each client store, list the runs of the last 60 days whose `env.python` starts with 3.8 or 3.9 (a `vmn-exp list <app> --query` on `env.python`; take the exact operator from sdk.md 'The query language'). Runs made with `--no-env` or `VMN_CAPTURE_ENV=0` carry no answer.
   - If any are found, the owner tells that client before the release; the item does not otherwise change, since the floor is decided.
2. **requires-python = ">=3.10"** in packages/vmn-exp/pyproject.toml and packages/vmn-exp-sdk/pyproject.toml. Core vmn's pyproject stays >=3.8 and is out of scope.
3. **The upgrading.md row** (F9 Behaviour changes): what changed, that pip on 3.8/3.9 keeps resolving to the last release that supported them (so those images stop getting fixes; nothing breaks at install), and the query from step 1 so an operator can check their own store.
4. **Code that exists only for Python below 3.10.** Remove in the same item, each under its existing tests:
   - storage/registry.py:102-106 `_storage_entry_points`: the `hasattr(found, "select")` branch and the `found.get(...)` fallback marked `# Python < 3.10` collapse to `entry_points(group=ENTRY_POINT_GROUP)` (covered by test_storage_uri_registry.py).
   - core/lineage_index.py:134-141 `_after`: a hand-written bisect because '3.8's has no key'; becomes `bisect.bisect_right(entries, idx, key=self._idx)` (covered by test_exp_lineage_core.py, test_exp_lineage_delta.py, test_exp_lineage_fanout.py).
   Found and deliberately left:
   - ui/thread_limiters.py (new in cddf6651): its docstring says the last anyio for Python 3.9 is 4.12 and 'Delete this module once anyio 4.15 is the floor'. uv.lock already resolves anyio 4.15.1 for >=3.10 (uv.lock:137-143), but anyio is not a direct dependency of the `ui` extra (it arrives through fastapi), so deleting the module means adding `anyio>=4.15` to the extra and deleting test_ui_thread_limiters.py. Report it as a follow-up; not part of F12.
   - storage/s3_base.py:127-131 `_six_digits` names 3.9 in its docstring, but `datetime.fromisoformat` only accepts other fraction lengths from 3.11, so it is still needed on 3.10.
   - `from typing import List, Optional, ...` in about twenty modules, and ruff.toml:6 `target-version = "py38"` with the UP035 ignore: style, not version-only code, and ruff.toml is shared with core vmn, which stays on 3.8. No change.
   - tests/test_requirements_docker.txt:10-13 (`python_version >= "3.9"` markers) is shared with core vmn. No change.
5. **Metadata.** Both pyprojects: keywords, classifiers (Development Status, one 'Programming Language :: Python :: 3.x' line per supported minor from 3.10, Topic :: Scientific/Engineering :: Artificial Intelligence) and [project.urls] Documentation (docs/vmn-exp/README.md), Changelog (packages/vmn-exp/CHANGELOG.md from F10), Issues and Source.
6. **Extras.** Give each extra a lower bound: the oldest version the code is exercised with, read from the test requirements and uv.lock; no upper caps unless a known break exists.
7. Run `uv lock` so uv.lock matches. Rewrite packaging.md's PyPI section to the present state after checking PyPI (not checked in this pass), keeping the placeholder history as one sentence.

**Tests first.**

- packages/vmn-exp/tests/test_workspace.py::test_both_exp_distributions_require_python_3_10_or_newer (reads the two pyproject files; red today)
- test_workspace.py::test_python_classifiers_match_requires_python (no classifier below the floor; red today, no classifiers)
- test_workspace.py::test_the_exp_distributions_declare_classifiers_keywords_and_urls (Documentation, Changelog, Issues present)
- test_workspace.py::test_every_exp_extra_requirement_has_a_lower_bound (self-references like vmn-exp-sdk[s3] exempt; red today on five requirements)
- packages/vmn-exp/tests/test_storage_uri_registry.py::test_plugin_schemes_are_read_from_the_entry_point_group_only (a recording fake put in place of `registry.entry_points`, the way the file's tests replace `registry._storage_entry_points` at :18 and :102; asserts it is called with `group=ENTRY_POINT_GROUP`; red today, the code calls it with no argument. The file's autouse fixture replaces `_storage_entry_points` itself (:18), so this test puts the real function back before calling it)
- the step 4 lineage change is a refactor under the three lineage test files named above; they stay green with no edit

**Files.** `packages/vmn-exp/pyproject.toml`, `packages/vmn-exp-sdk/pyproject.toml`, `packages/vmn-exp-sdk/src/vmn_exp/storage/registry.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/lineage_index.py`, `packages/vmn-exp/tests/test_workspace.py`, `packages/vmn-exp/tests/test_storage_uri_registry.py`, `docs/vmn-exp/upgrading.md`, `docs/packaging.md`, `uv.lock`

**Risk.** A 3.8 or 3.9 job image keeps installing the last 0.1.x that supported it and stops receiving fixes, silently; step 1 and the upgrading.md row are the only warning, so do step 1 before the release, not after. The repo cannot show which interpreters clients run. The floor is asserted by metadata, not exercised: CI runs one Python and no multi-Python matrix is added here. The workspace has one uv.lock (`requires-python = ">=3.8"`, uv.lock:3) for three members; with two members at >=3.10 and core vmn at >=3.8, how `uv lock` resolves the workspace floor was not tried. If it narrows the lock to >=3.10, core vmn's own wheel metadata is still >=3.8 but its dev lock no longer covers 3.8/3.9; report what `uv lock` does before committing it. Lower bounds on extras can clash with pinned training environments, so keep them as low as the tests justify. The stamp's version_backends regexes match only the version and pin lines (.vmn/vmn_exp/conf.yml:14-17) and are unaffected.

**Owner decision (2026-11-11).** Both packages require Python >=3.10. It ships in a patch release with an upgrading.md row, after the job-image interpreters have been checked.

**Evidence.** `packages/vmn-exp/pyproject.toml:13`; `packages/vmn-exp/pyproject.toml:22-33`; `packages/vmn-exp/pyproject.toml:40-41`; `packages/vmn-exp-sdk/pyproject.toml:13`; `packages/vmn-exp-sdk/pyproject.toml:21-31`; `packages/vmn-exp/src/vmn_exp/ui/shell_meta.py:25`; `packages/vmn-exp-sdk/src/vmn_exp/storage/registry.py:102-106`; `packages/vmn-exp-sdk/src/vmn_exp/core/lineage_index.py:134-141`; `packages/vmn-exp/src/vmn_exp/ui/thread_limiters.py:1-12`; `packages/vmn-exp-sdk/src/vmn_exp/storage/s3_base.py:127-131`; `packages/vmn-exp-sdk/src/vmn_exp/core/env.py:232-250`; `docs/vmn-exp/experiments.md:622-634`; `ruff.toml:6`; `tests/test_requirements_docker.txt:10-13`; `tests/run_install_matrix.sh:1-16`; `Dockerfile:1-3`; `ci/README.md:282`; `uv.lock:3`; `uv.lock:101-143`; `docs/vmn-exp/ui.md:246`; `docs/vmn-exp/ui.md:263-269`; `docs/packaging.md:188-198`; `release_exp.sh:27`

<a id="f13"></a>
### F13. Protect the solo-user experience: a small-store contract test on the new default board and a 'Solo impact' line in every plan from 37 on

P2 · S · depends on F8, plan 38 A6

**Problem.** PRODUCT.md names solo engineers as primary and says the team server 'must never make the single-user case worse' (:13-15, principle 3 at :57), but plans 31, 33 and 34 are each driven by one client's large store (index rows 31, 33, 34 name fgm), and the CI load harness's smallest profile is 500 runs with 5 live jobs (uiload/scenario.py:71) with latency budgets only. The solo user's first screen is decided by plan 38 A6: an app with no outer runs opens on the runs board with metric columns. That choice is made in the web app from two server answers: the facets' `jobs`/`singles` counts (jobsKind.ts:15, :24-28) and the runs-board page, which SinglesView requests with `top=singles` (SinglesView.tsx:36-38). On the server nothing pins those two answers for a store of 0, 1 or a dozen plain runs.

**Approach.**

(1) Unit test on the existing fakes (the Fleet + LeaderboardCache pattern of test_ui_jobs_view.py:16-31): for fleets of 0, 1 and 12 single runs with no parent,
   - the top counts are `{"jobs": 0, "singles": N}` (leaderboard_top_counts.py:13-22, served through LeaderboardAnswers.top_counts, leaderboard_answers.py:85-89). This is the answer that makes A6 pick the runs board;
   - the runs-board page (`cache.page(snap, SCHEMA, top="singles")`) returns every run in `rows` and `total == N`, and each row's `metrics` holds the schema's primary metric, so the board's metric column has something to show. `Fleet.append` draws metric values at random and sometimes leaves `loss` out (leaderboard_fleet.py:59-66), so the test sets each run's value with `fleet.edit(i, values={"loss": ...})`, as test_ui_attention_bench.py:55 does.
(2) One end-to-end test over a temp-dir store through TestClient(create_app(manager)) (pattern run_code_seed.py:83-90), 12 runs written with the SDK, each logging one metric: the facets request and the `top=singles` experiments request need no token on a standalone app, the facets say `jobs: 0, singles: 12`, the page returns all 12 rows with the metric, and carries no `indexing` state once the first index is built. No uvicorn thread and no load harness.
(3) docs/plans/README.md gains a five-line 'Solo check' (fresh local store, no server.yml, no token, no outer runs; one command to open the UI; no new setup step; the runs board shows the runs and their metrics; cold start not slower), and one rule under it: a plan may carry a negative solo impact only when its 'Solo impact' line states the trade-off and a setting keeps the solo default. Every plan from 37 on carries a 'Solo impact:' line; plans_index_problems (F8) reports a plan numbered 37 or higher without one. Plans 37-44 already have the line; plan 36 (upstream) is exempt.
The web side of the same promise is plan 38 A6's own tests (JobsKind.test.tsx and ExperimentsPage.test.tsx), and they run in CI once plan 42 E14a lands. This item adds no web test, no behaviour change and no latency budget. If either test is red, that is a product bug to report, with its fix decided then.

**Tests first.**

- packages/vmn-exp/tests/test_solo_store_board.py::test_a_store_of_single_runs_counts_no_outer_runs (parametrised 0, 1, 12; Fleet + LeaderboardCache fakes)
- test_solo_store_board.py::test_the_runs_board_lists_every_single_run_with_its_primary_metric (same fakes, `top="singles"`)
- packages/vmn-exp/tests/test_solo_store_api.py::test_twelve_sdk_runs_in_a_fresh_local_store_are_all_on_the_runs_board_without_a_token (temp dir + TestClient; after the two unit tests)
- packages/vmn-exp/tests/test_plans_index.py::test_a_plan_from_37_on_without_a_solo_impact_line_is_reported (in-memory)

**Files.** `packages/vmn-exp/tests/test_solo_store_board.py`, `packages/vmn-exp/tests/test_solo_store_api.py`, `packages/vmn-exp/tests/test_plans_index.py`, `docs/plans/README.md`

**Risk.** The unit tests pin current server behaviour and may be green on first run; the implementer shows each fails under a deliberate break. They are valid before A6 lands, since A6 changes only which board the web app picks; the 'Solo check' wording about the runs board is true only after A6, so the README lines land with or after it. The existing fixture pins the clock by patching `status._now` (test_ui_jobs_view.py:18); follow it unless plan 44 has given the board an injected clock by then. The end-to-end test uses a temp dir and an in-process app, so it runs in the normal parallel pass. The owner's answer covers the test and the line; the rule for a negative solo impact in step (3) was not asked separately and is this item's wording.

**Owner decision (2026-11-11).** A small-store contract test and a 'Solo impact' line in every plan from 37 on, written against the new default board (plan 38 A6).

**Evidence.** `PRODUCT.md:13-15`; `PRODUCT.md:57`; `docs/plans/README.md (rows 31, 33, 34)`; `packages/vmn-exp/tests/uiload/scenario.py:71`; `docs/vmn-exp/ui.md:444-448`; `packages/vmn-exp/webui/src/pages/Experiments/experimentsView.ts:41`; `packages/vmn-exp/webui/src/pages/Experiments/jobsKind.ts:15-28`; `packages/vmn-exp/webui/src/pages/Experiments/SinglesView.tsx:1-4`; `packages/vmn-exp/webui/src/pages/Experiments/SinglesView.tsx:36-38`; `packages/vmn-exp/webui/src/pages/Experiments/__tests__/JobsKind.test.tsx:94-102`; `packages/vmn-exp/src/vmn_exp/ui/leaderboard_top_counts.py:13-22`; `packages/vmn-exp/src/vmn_exp/ui/leaderboard_answers.py:85-89`; `packages/vmn-exp/src/vmn_exp/ui/leaderboard_cache.py:511-513`; `packages/vmn-exp/src/vmn_exp/ui/leaderboard_scope.py:29-46`; `packages/vmn-exp/src/vmn_exp/ui/leaderboard_answers.py:62-63`; `packages/vmn-exp/tests/leaderboard_fleet.py:59-84`; `packages/vmn-exp/tests/leaderboard_fleet.py:94-96`; `packages/vmn-exp/tests/test_ui_attention_bench.py:55`; `packages/vmn-exp/tests/test_ui_jobs_view.py:16-37`; `packages/vmn-exp/tests/run_code_seed.py:83-90`; `docs/plans/38-vmn-exp-first-run.md (A6)`

<a id="f14"></a>
### F14. Roadmap decision record for the feature gaps

P2 · S · depends on F2, F3

**Problem.** The comparison pages can only say 'absent' for ten gaps, with no word on which are coming, which are not, and which are refused by design. The owner has now answered all ten.

**The record (owner, 2026-11-11).**

| Gap | Decision | Where it goes |
|---|---|---|
| LightGBM and CatBoost autolog | **Build** | [F16](#f16) |
| ASHA / successive-halving early stopping for sweeps | **Build** | [F17](#f17) |
| Notebook display of the run object | **Build** | [F18](#f18); the guide is plan 38 A9 |
| Code-less run (notebook, Colab, evaluation outside a checkout) | **Build**, explicit opt-in only | plan 38 A10 |
| HTML and audio media | **Deferred** | not planned now; media stays table, image, histogram (sdk/run_media.py:153-180) |
| W&B importer | **Deferred** | after vmn-vs-wandb.md (F3), when a migrating user asks |
| Per-project permissions | **Deferred** | the answer today is one workspace per project |
| Logging over an HTTP endpoint | **Rejected** | by design: plan 11 invariant I4 (:63) and §9 (:561); offline recording plus `vmn-exp push` is the documented answer |
| LLM / trace logging | **Declined** | a different product |
| Hosted service | **A business decision** | not an engineering item; the docs keep making no availability claim (PRODUCT.md:51) |

Not asked and unchanged: full Hyperband brackets and video media stay unplanned; plain-torch loop autolog stays out by design (autolog.py:44-48), with `watch()` plus `log_metric` as the answer.

**Approach.**

This section is the record; no separate plan file is written (the draft's `36-roadmap-gaps.md` number was taken upstream). What is left is docs, in the shipped pages, in their own words and with no dates:
- vmn-vs-mlflow.md: the Autologging row (:35) and the 'LLM/prompt tracing' row (:54) say what is planned and what is not offered; the HTTP-logging paragraph (:148-151) says 'by design' and names offline recording and `vmn-exp push`.
- vmn-vs-wandb.md (F3): its 'where W&B is the right tool' list uses the same three labels: planned, not planned, not offered by design.
- sweeps.md:172-173 is rewritten by F17 when ASHA ships, not before.
The shipped docs do not link into docs/plans/ (no page under docs/vmn-exp does today, and the wheel ships only docs/vmn-exp), so the labels are stated in the pages themselves. docs/plans/README.md's row for plan 43 names F14 as the roadmap record (F8 adds the row).

**Tests first.**

- No new test. F4's link check covers the edited pages and F2's tests cover the comparison's code-tied rows. A string test for the labels would only restate the edit.

**Files.** `docs/vmn-exp/vmn-vs-mlflow.md`, `docs/vmn-exp/vmn-vs-wandb.md`, `docs/plans/README.md`

**Risk.** None at runtime. Saying 'planned' in user docs is a commitment without a date; keep it to the three items that have a drafted plan (F16, F17, F18) and the one in plan 38 (A10). A written 'no' on HTTP logging and LLM tracing is a positioning choice the owner made.

**Owner decision (2026-11-11).** Build: LightGBM/CatBoost autolog, ASHA early stopping, notebook repr. Deferred: HTML/audio media, W&B importer, per-project permissions. Rejected: an HTTP logging endpoint. Declined: LLM/trace logging. Hosted stays a business decision. The code-less run is plan 38 A10.

**Evidence.** `docs/plans/11-central-server.md:11`; `docs/plans/11-central-server.md:63`; `docs/plans/11-central-server.md:561`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run_media.py:153-180`; `docs/vmn-exp/sweeps.md:172-173`; `docs/vmn-exp/vmn-vs-mlflow.md:35`; `docs/vmn-exp/vmn-vs-mlflow.md:54`; `docs/vmn-exp/vmn-vs-mlflow.md:148-151`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/autolog.py:44-48`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/autolog.py:351-364`; `packages/vmn-exp-sdk/src/vmn_exp/integrations/torch_watch.py:144`; `PRODUCT.md:51`

<a id="f16"></a>
### F16. LightGBM and CatBoost autolog

P2 · M

**Problem.** `autolog()` covers sklearn, xgboost, keras/tensorflow, lightning and transformers (SUPPORTED_FRAMEWORKS, autolog.py:351-364). The two other gradient-boosting libraries in everyday use are missing, so a LightGBM or CatBoost user gets nothing from `autolog()` and the comparison page says so (vmn-vs-mlflow.md:35).

**Approach.**

Follow the extension point the module documents (autolog.py:29-38): one adapter per framework, registered in SUPPORTED_FRAMEWORKS under the import name, in a new module sdk/autolog_gbdt.py (one module per framework family, as autolog_keras.py is). Both libraries are patched only when the script imports them (autolog.py:129-164 patches a module already in sys.modules and hooks the rest through import_hooks), so the SDK gains no dependency.

An adapter answers the recording path's questions (_Adapter, autolog_adapter.py:36-61; defaults in `_adapter`, :64-94):

| | LightGBM (`lightgbm`) | CatBoost (`catboost`) |
|---|---|---|
| discover | `_fit_owners` over `LGBMClassifier`, `LGBMRegressor`, `LGBMRanker`: the scikit-learn wrappers only, the same shape as `_discover_xgboost` (autolog_sklearn.py:36-46) | `_fit_owners` over `CatBoostClassifier`, `CatBoostRegressor`, `CatBoostRanker`, `CatBoost` |
| params | the default `get_params()` (autolog_adapter.py:176-179) | the default `get_params()` |
| metrics | own extractor: the training `score` under the existing `_wants_training_score` rule (:199-204); never `best_score_` | the same |
| series | per-iteration eval results, one series per dataset and metric, named `<dataset>_<metric>`; read from the fitted estimator's `evals_result_` | the same, read from `get_evals_result()` |
| fitted_params | `best_iteration` when the estimator has one | `best_iteration` from `get_best_iteration()` when it is not None |
| save | the default pickle (:169-173) | `subject.save_model(base + ".cbm")`, returning the path (the save hook's contract, :164-173) |

Why `metrics` is not the default: `_score_metric` logs `best_score_` as `best_cv_score` (autolog_adapter.py:182-196), which is right for a scikit-learn search. On these two libraries `best_score_` is the eval-set results, not a cross-validation score, so the default would publish a wrong name or drop a non-number. `_log_metric_series` already logs a curve one step at a time and its last point is the final value (autolog.py:304-320), so no separate final-metric extractor is needed. The native APIs (`lightgbm.train`, `catboost.train`) are left alone for the reason autolog_sklearn.py:41-44 gives for `xgboost.train`. Nested fits record once (the outermost call only, autolog.py:21-27), so a classifier whose `fit` calls its base class's `fit` is one record.

Docs: two rows in the sdk.md autologging table (:524-529) and the feature matrix under it; vmn-vs-mlflow.md:35. `vmn-exp skill` does not list frameworks, so agent-skill.md is not regenerated.

**Tests first.** New file packages/vmn-exp/tests/test_exp_autolog_gbdt.py, on fakes only: a counterfeit `lightgbm` / `catboost` module injected into `sys.modules` with small fake estimator classes, and a FakeRun on the open-run stack, exactly as test_exp_autolog.py does for sklearn (:73-84, :141-147). No real library is imported.

- test_a_lightgbm_fit_records_its_hyperparameters_under_the_lightgbm_label (red today: no adapter, nothing recorded)
- test_lightgbm_eval_results_arrive_as_one_series_per_dataset_and_metric (the fake's `fit` sets `evals_result_ = {"valid_0": {"l2": [3.0, 2.0, 1.0]}}`; expect three `log_metrics` calls with `lightgbm_valid_0_l2`)
- test_a_dict_best_score_is_never_logged_as_best_cv_score
- test_a_lightgbm_fit_without_an_eval_set_logs_no_series
- test_a_catboost_fit_records_get_evals_result_per_iteration
- test_catboost_log_models_saves_through_save_model (the fake's `save_model` writes a file; the run receives one `.cbm` artifact)
- test_autolog_imports_neither_lightgbm_nor_catboost (after `autolog()`, neither name is in `sys.modules`; the pattern of test_exp_autolog.py:188-192)
- test_a_failing_eval_result_reader_does_not_break_fit (the `_guarded` rule, autolog_adapter.py:97-101)

Then, in packages/vmn-exp/tests/test_exp_autolog_real.py, one test per library behind `pytest.importorskip`, as the xgboost tests there are (:264): a real `LGBMRegressor` and a real `CatBoostRegressor` fitted with an eval set record params and a validation curve.

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/autolog_gbdt.py` (new, under 150 lines), `packages/vmn-exp-sdk/src/vmn_exp/sdk/autolog.py` (two registry lines and the import), `packages/vmn-exp/tests/test_exp_autolog_gbdt.py` (new), `packages/vmn-exp/tests/test_exp_autolog_real.py`, `docs/vmn-exp/sdk.md`, `docs/vmn-exp/vmn-vs-mlflow.md`

**Risk.** The attribute shapes (`evals_result_`, `best_score_`, `best_iteration_` on LightGBM; `get_evals_result()`, `get_best_iteration()`, `save_model` on CatBoost; which class defines `fit`) come from the libraries' public scikit-learn-style API, not from this repo: neither library is installed or referenced here. The fakes encode those shapes, so a wrong assumption passes the unit tests and fails only the real-library tests. Those skip unless the library is installed, and packages/vmn-exp/tests/test_requirements.txt lists xgboost but neither of these; adding both makes the suite's install heavier, so decide that when the item starts and say which was chosen. CatBoost's `get_params()` returns only explicitly set parameters, so its params row is shorter than sklearn's; document it rather than work around it. Solo impact: none; nothing changes unless the script imports one of the two libraries after calling `autolog()`.

**Owner decision (2026-11-11).** Build it.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/autolog.py:21-48`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/autolog.py:129-164`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/autolog.py:304-320`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/autolog.py:351-364`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/autolog_adapter.py:36-61`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/autolog_adapter.py:64-101`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/autolog_adapter.py:164-204`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/autolog_adapter.py:230-257`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/autolog_sklearn.py:36-50`; `packages/vmn-exp/tests/test_exp_autolog.py:73-84`; `packages/vmn-exp/tests/test_exp_autolog.py:141-147`; `packages/vmn-exp/tests/test_exp_autolog.py:188-192`; `packages/vmn-exp/tests/test_exp_autolog_real.py:18`; `packages/vmn-exp/tests/test_exp_autolog_real.py:264`; `packages/vmn-exp/tests/test_requirements.txt:10`; `docs/vmn-exp/sdk.md:524-529`; `docs/vmn-exp/vmn-vs-mlflow.md:35`

<a id="f17"></a>
### F17. ASHA early stopping for sweeps

P2 · M

**Problem.** A sweep has one early-termination rule, the median rule (`early_terminate: {type: median}`): spec.py:179-189 refuses any other type, and sweeps.md:172-173 says 'hyperband is not supported'. The median rule stops the worse half at best. For a search over many configurations where most are poor, successive halving stops far more of them early, and it is the rule W&B and Ray users expect to find.

**Approach.**

Add `type: asha` beside `median`, as the stopping variant of asynchronous successive halving. The agent can only stop a running trial (SIGTERM through the supervisor, sweeps.md:160-165); it cannot pause and resume one, so there is no promotion queue, and none is needed: a trial that is not stopped simply keeps running.

*The rule (pure function).* Rungs are the steps `min_iter * eta**k` for k = 0, 1, 2, ... When a check runs, take the highest rung `r` the trial has reached (its latest step is `>= r`). Compare its best value up to `r` with the best-up-to-`r` of every other trial that has reached `r` (its latest step is `>= r` and it has a point at or before `r`; `_best_until` on a trial whose first step is past `r` would index from the end, so such a trial is not counted). With `n` values at the rung, the trial's own included:
- if `n < eta`, keep running (asynchronous: never wait for peers);
- otherwise stop the trial unless its value is among the best `n // eta` (a tie keeps it).
Only the highest reached rung is judged, so a trial that passed rung `r` is never stopped later for rung `r`, whatever arrives there afterwards. This is the same input the median rule takes, each trial's `(step, value)` points, and it reuses `_bests` and `_best_until` (early_stop.py:46-54).

*Spec.* `_early_terminate` (spec.py:179-189) accepts `median` or `asha`. For `asha` the keys are `min_iter` (the first rung; the shared default 3, spec.py:17), `eta` (an integer >= 2, default 3) and `check_interval_sec`; `min_trials` does not apply (`eta` is the minimum). The error for another type reads 'must be median or asha'; `hyperband` stays refused (test_sweep_spec.py:49 keeps passing unchanged).

*Code.* In core/sweep/early_stop.py: `asha_should_stop(own, others, goal, min_iter, eta)`, an `AshaStopper` with the three methods the agent calls on `MedianStopper` (`due`, `past_min_iter`, `should_stop`, early_stop.py:57-83; the shared `due` moves to a small base so it is not written twice), and `stopper_for(spec)` that picks by `spec["early_terminate"]["type"]`. In cli/sweep/agent.py, `_EarlyStopCheck.__init__` (:118-126) calls `stopper_for(spec)` instead of building `MedianStopper`, and the log line at :132 names the rule's type instead of the fixed '(median rule)'. Nothing else in the check changes: it already reads peers through PeerPoints off the heartbeat thread (:110-156), and a stopped trial already gets `end_reason: stopped` and derives as succeeded (sweeps.md:167-172).

*UI and docs.* The sweep card prints `{type} after {min_iter} steps` from the spec (SweepSection.tsx:40-42), which reads correctly for `asha` with no change. sweeps.md: the spec example (:35-36), and 'Early termination (median rule)' (:158-173) becomes 'Early termination' with one subsection per rule; the last sentence becomes 'Full Hyperband (several brackets) is not supported; `asha` is one bracket.' vmn-vs-wandb.md (F3) lists it.

**Tests first.** All pure, on synthetic series built with the file's `_curve` helper; no storage, no agent, no clock.

- packages/vmn-exp/tests/test_sweep_early_stop.py::test_asha_stops_a_trial_outside_the_top_fraction_at_its_rung (red today: no such function)
- test_sweep_early_stop.py::test_asha_keeps_a_trial_inside_the_top_fraction
- test_sweep_early_stop.py::test_asha_never_stops_while_fewer_than_eta_trials_reached_the_rung
- test_sweep_early_stop.py::test_asha_judges_only_the_highest_rung_the_trial_reached
- test_sweep_early_stop.py::test_asha_compares_best_so_far_up_to_the_rung_not_later_steps
- test_sweep_early_stop.py::test_asha_with_a_maximize_goal_flips_the_rule
- test_sweep_early_stop.py::test_a_tie_at_the_cut_keeps_the_trial
- test_sweep_early_stop.py::test_a_peer_whose_first_step_is_past_the_rung_is_not_counted
- test_sweep_early_stop.py::test_stopper_for_picks_the_rule_named_by_the_spec
- packages/vmn-exp/tests/test_sweep_spec.py::test_asha_early_terminate_defaults_to_eta_3
- test_sweep_spec.py::test_an_asha_eta_below_2_is_refused
- test_sweep_spec.py::test_an_unknown_early_terminate_type_names_both_rules

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/core/sweep/early_stop.py`, `packages/vmn-exp-sdk/src/vmn_exp/core/sweep/spec.py`, `packages/vmn-exp/src/vmn_exp/cli/sweep/agent.py`, `packages/vmn-exp/tests/test_sweep_early_stop.py`, `packages/vmn-exp/tests/test_sweep_spec.py`, `docs/vmn-exp/sweeps.md`

**Risk.** A polled check can run after a trial has passed a rung boundary, so the trial is judged at its new highest rung and the skipped rung is never judged for it; with a long `check_interval_sec` and short rungs ASHA stops fewer trials than the textbook version. That errs toward keeping trials, and the docs say so. Early in a sweep few trials have reached any rung, so the first `eta - 1` trials are never stopped. `_EarlyStopCheck.__call__` reads `time.monotonic()` directly (agent.py:134); this item does not add a clock call, and moving that one behind an injected clock belongs to plan 44, which also edits this file. Plan 38 A12 (sweep trials adopt the wrapper's run) touches the same agent module; the stopper reads `metric_source` rows (agent.py:146-153), so check its tests against whichever lands second. Solo impact: none unless a sweep spec asks for `type: asha`.

**Owner decision (2026-11-11).** Build ASHA early stopping. Full Hyperband brackets stay out.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/core/sweep/early_stop.py:1-10`; `packages/vmn-exp-sdk/src/vmn_exp/core/sweep/early_stop.py:29-54`; `packages/vmn-exp-sdk/src/vmn_exp/core/sweep/early_stop.py:57-83`; `packages/vmn-exp-sdk/src/vmn_exp/core/sweep/spec.py:17`; `packages/vmn-exp-sdk/src/vmn_exp/core/sweep/spec.py:44-45`; `packages/vmn-exp-sdk/src/vmn_exp/core/sweep/spec.py:179-189`; `packages/vmn-exp/src/vmn_exp/cli/sweep/agent.py:97-108`; `packages/vmn-exp/src/vmn_exp/cli/sweep/agent.py:110-156`; `packages/vmn-exp/tests/test_sweep_early_stop.py:1-31`; `packages/vmn-exp/tests/test_sweep_spec.py:49`; `packages/vmn-exp/tests/test_sweep_spec.py:76-79`; `packages/vmn-exp/webui/src/components/SweepSection.tsx:40-42`; `packages/vmn-exp/webui/src/apiSweep.ts:11`; `docs/vmn-exp/sweeps.md:35-36`; `docs/vmn-exp/sweeps.md:158-173`

<a id="f18"></a>
### F18. A notebook repr for the run object

P3 · S · pairs with plan 38 A9

**Problem.** In a notebook, a cell that ends with `run` or with `start_run(...)` prints `<vmn_exp.sdk.run.Run object at 0x...>`: no class in the SDK defines `__repr__` or `_repr_html_`. The object already holds what the user wants to see: `app_name`, `id` and `name` (run.py:337-339) and the in-memory run state (`state`, `exit_code`, `started_at`; run.py:399-420). Plan 38 A9 writes the notebook guide; this is the one code change that guide wants.

**Approach.**

A new module sdk/run_repr.py with two pure functions over plain values, and two one-line methods on `Run` that call them with the object's fields:
- `text(app_name, run_id, name, state, exit_code)` returns one line, for example `<Run my_app 0.1.2-dev.3f9a.r4 "baseline" running>` or `... finished exit 1>`. `Run.__repr__` uses it, so the debugger, logs and a plain REPL benefit too.
- `html(app_name, run_id, name, state, exit_code)` returns a small block: the app, the run id, the name, the state, and the command that shows the run (`vmn-exp show <app> -v <id>`, the form experiments.md:777 documents), every value HTML-escaped. `Run._repr_html_` uses it; Jupyter calls that method by name, so nothing imports IPython.
`NoOpRun` (ranks.py:47-62, what `start_run()` returns on a non-zero rank or in disabled mode) gets a `__repr__` saying it records nothing and why (`disabled` or the rank).

The repr reads only fields already in memory. It never touches storage and never raises: a repr is called by debuggers and by error formatting.

There is no dashboard link. The SDK knows no dashboard address: the only URL settings are server-side (`VMN_UI_PUBLIC_URL`, ui/config.py:26), and plan 11 keeps jobs from needing a server URL (docs/plans/11-central-server.md:17). A link would need a new client-side setting; that is a separate decision and not part of this item.

Docs: one paragraph in sdk.md's `start_run` section (near :112-118) and the screenshot-free example in plan 38 A9's notebooks.md.

**Tests first.** New file packages/vmn-exp/tests/test_sdk_run_repr.py; the first five call the pure functions with plain values and need no run, no storage and no git.

- test_the_text_repr_names_the_app_the_id_the_name_and_the_state (red today: no module)
- test_a_finished_run_reads_finished_with_its_exit_code
- test_a_run_without_a_name_has_no_empty_quotes
- test_the_html_repr_escapes_the_run_name (a name of `<script>` appears escaped)
- test_the_html_repr_gives_the_show_command_for_this_run
- test_a_noop_run_says_it_records_nothing
- test_repr_of_an_open_run_delegates_and_reads_no_storage (a `Run(storage, APP, VERSTR, 60)` that is never opened, the way test_sdk_finalize_frozen_append.py:33 builds one, over a storage stand-in that records every attribute access; nothing is recorded across `repr(run)` and `run._repr_html_()`)

**Files.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/run_repr.py` (new, under 60 lines), `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py`, `packages/vmn-exp-sdk/src/vmn_exp/sdk/ranks.py`, `packages/vmn-exp/tests/test_sdk_run_repr.py` (new), `docs/vmn-exp/sdk.md`

**Risk.** A `Run` is constructed without `_open()` in existing tests (test_sdk_finalize_frozen_append.py:33, test_sdk_compaction.py:49), there over a LocalSnapshotStorage in a temp dir. Whether the constructor itself touches storage (it hands `storage` to a state publisher and a log buffer, run.py:363-370) was not traced; if it does, the last test takes its baseline after construction, or uses the temp-dir storage, and the pure-function tests carry the behaviour. The state shown is this process's view (`_state`), not the derived status another reader would compute (a run can read `stuck` elsewhere while it prints `running` here); the repr says `running`, not `status: running`. run.py is 889 lines and is edited by plans 40, 41 and 44; this adds two methods and one import, so rebase is trivial but expected. Solo impact: positive, and no change outside interactive use.

**Owner decision (2026-11-11).** Build a notebook repr for the run object.

**Evidence.** `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:310-313`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:337-339`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:363-370`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:399-420`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/run.py:535`; `packages/vmn-exp-sdk/src/vmn_exp/sdk/ranks.py:47-62`; `packages/vmn-exp/tests/test_sdk_finalize_frozen_append.py:33`; `packages/vmn-exp/tests/test_sdk_compaction.py:49`; `grep __repr__|_repr_ packages/vmn-exp-sdk/src/vmn_exp/sdk/ (no match)`; `packages/vmn-exp/src/vmn_exp/ui/config.py:26`; `docs/plans/11-central-server.md:17`; `docs/vmn-exp/experiments.md:777`; `docs/vmn-exp/sdk.md:112-118`; `docs/plans/38-vmn-exp-first-run.md (A9)`

## Dropped

<a id="f15"></a>
- **F15. Run the web UI unit tests in CI.** Not a plan 43 item any more: it is [plan 42 E14a](42-vmn-exp-server-security-api.md#e14a), decided as one blocking CI stage for the web tests and ESLint after a one-off fix pass. F13 relies on it for the web half of the solo first screen.
- **F9's `release_exp.sh` release-mode argument.** Dropped by the patch-only decision: there is no other mode to pass.
- **F14's separate plan file (`docs/plans/36-roadmap-gaps.md`).** The owner answered every row, so the record is F14 itself and the three 'build' answers are F16-F18; number 36 was taken upstream by the fgm plan.

## Review findings corrected or dropped

- **Finding 7 (part): relax the vmn-exp -> vmn-exp-sdk == pin because it forces job images to upgrade in lockstep** The pin (packages/vmn-exp/pyproject.toml:19) constrains only an environment where vmn-exp itself is installed; an SDK-only job image is unaffected. Relaxing it is unsafe: vmn-exp imports 140 distinct SDK-internal modules (16 imports of private names) from the same PEP 420 namespace, and build_dist.sh:34-38 and .vmn/vmn_exp/conf.yml:16-17 rewrite the pin on every release. The cross-version contract is the store (LAYOUT, RECORD_FORMAT_VERSION); F11 documents and tests that instead.
- **Finding 1 (part): PRODUCT.md carries the outdated 'No server, no database' headline** PRODUCT.md:24 says 'no server or database is required' and describes the server's database as a throwaway cache, which matches the revised rule in docs/plans/README.md. Its ~100k scale lines (:30, :58) are reworded in F2. README.md:7 ('No server. No database.') describes core vmn and is correct there.
- **Finding 3 (part): plan 20 targets W&B, so a W&B importer is owed** docs/plans/20-flows-beat-wandb-mlflow.md is about dashboard flows; its only mentions of 'import' are not about a W&B importer. The missing comparison page is real (F3); the importer is deferred (F14).
- **Finding 4 (part): experiments.md uses the pre-split names 'throughout'; the stuck rule is in four places; install in five** The bare `exp <action>` names are in 15 lines of the 2,116, not throughout; the `exp` prefix is still an accepted alias (experiments.md:509-511) and `runner: exp run` (:215) shows a stored value and stays. The duplication is slightly wider than stated: the stuck formula is in five vmn-exp docs plus CLAUDE.md:219, and full install blocks in more than five. Planned as F6 with those corrections.
- **Finding 4 (part, as the draft planned it): split the API out of ui.md** Not refuted as a problem (1,967 lines, no TOC), but the draft's split was not safe as written: '### Similar runs' (ui.md:1857) is inside the API section and test_docs_similar_statements.py:49 and :116 read it from ui.md, and 13 cross-doc links target API anchors. The owner chose the split; F5 lists every test line and link that moves with it.
- **Finding 10 (part): there is no small-store smoke test in CI** The uiload smoke profile (500 runs, 5 live jobs; uiload/scenario.py:71) runs in CI's serial pass (test_uiload_profile.py:12-13, ci/pipeline.py:152), and the web app already has tests for an app without outer runs (JobsKind.test.tsx:94-118). The real gaps are that CI never runs the web tests (now plan 42 E14a) and that nothing pins the server answers for 0/1/12-run stores (F13).
- **Finding 8 (part): docs recommend free-threaded 3.14t+** ui.md:244-247 recommends 3.15t; 3.14t appears only in the measurements (:256-257). The requires-python problem is real regardless: ui/shell_meta.py:25 uses functools.cache, which needs 3.9. The owner set the floor at 3.10 for both packages (F12).
- **Finding 6 (part): use vmn's own conventional-commits changelog feature** publisher.py:582-584 groups every commit since the app's tag with no path filter, so in this monorepo it would list core vmn commits under vmn-exp, and it requires conventional_commits, which also changes release-mode resolution for the app. F10 calls git-cliff directly with include paths instead; the release cadence and missing changelog themselves are confirmed (39 vmn_exp tags, 0.1.0 on 2026-09-28 to 0.1.37 on 2026-11-10, no CHANGELOG or cliff.toml in the repo).

## Non-goals

- Any change to ui/jobs.py _metric_args or storage/buffered.py _close(); both were fixed separately (859da19b, 59becdd5)
- Implementing the deferred, rejected or declined gaps of F14 (HTML/audio/video media, a W&B importer, per-project permissions, HTTP ingest, LLM tracing, a hosted service, full Hyperband). The three 'build' answers are F16-F18; the code-less run is plan 38 A10
- A dashboard link in the notebook repr (F18): the SDK has no dashboard address setting
- Relaxing or removing the vmn-exp-sdk == pin, or giving the two exp packages separate versions
- Rewriting the content of experiments.md or of the API reference; F5 moves the API text without changing its wording
- Adding a path filter to core vmn's changelog.path feature, or enabling conventional_commits for the vmn_exp app
- Rewriting commit history or adding a commit-message lint
- Changing core vmn's pyproject (requires-python, classifiers), ruff.toml's py38 target, or core vmn docs
- Deleting ui/thread_limiters.py (F12 names it as a follow-up)
- Hand-editing docs/vmn-exp/agent-skill.md (generated from cli/skill.py)
- A docs site generator, versioned docs, or link checking over the network
- New latency budgets or performance work for small stores; F13 pins behaviour only
- Adding a multi-Python CI matrix; F12 states the floor and names the gap
- A minor or major release, moving to 1.0, or promising API stability beyond the patch-only rules in F9

## What the critic changed in the draft

- F5 reduced from 'split the API into ui-api.md' to 'TOC + break the long bullet'. The split breaks test_docs_similar_statements.py:49 and :116 (they read '### Similar runs' from ui.md, and that heading is at ui.md:1827 inside the API section) and about 13 cross-doc anchors; the draft's risk note said only 'grep the tests'. The owner has since chosen the split, and F5 is rewritten for it (size M again).
- F10 redesigned. The draft parsed 'Would have stamped X' from `vmn stamp --dry-run` (a logger line, commands.py:357-358), committed before the stamp (a stray local commit if the stamp fails) and used --prepend (not idempotent, separate backfill). Now: full regeneration from tags through a `make _changelog` target after upload; backfill is the same command; the release-script test needs only the existing logging `make` stub. Added one real-git test of the path and tag scoping, which is the actual risk and was untested in the draft. The before/after-tag trade-off was put to the owner, who chose after.
- F9 policy and ratchet corrected. 'A records bump must be a minor' contradicts shipped behaviour: records 18 -> 19 and 19 -> 20 were in-place upgrades (server.md:151-158; constants at tags 0.1.30/0.1.35/0.1.36 checked with git show). Any bump needs an upgrading.md row; a layout, record-format or full-reload change needs more (F9 rule 5; with patch-only releases there is no minor trigger). The 'grandfathered' flag is dropped as unnecessary, and the backfill is limited to what the tags prove.
- F13 rewritten. The draft drove a uvicorn-thread harness (uiload/inproc_server.py) and asserted 'the default view' on the server, but the default is chosen in the web app (experimentsView.ts:41; fallback tested in JobsKind.test.tsx:94-101; plan 38 A6 has since changed that default, and F13 follows it). The first test is now a true unit test on the existing Fleet/LeaderboardCache fakes, with one TestClient end-to-end test; the speculative 'fix the default if it hides single runs' and the conditional slo budget are removed. Size M -> S.
- Added F15 (P1): CI never runs the web UI unit tests (527 test files; ci/pipeline.py:149 only builds the bundle; stage list at :232). This is the cheapest real protection for the solo first screen and the draft did not notice it. It is now plan 42 E14a.
- F8 widened and resized. The draft missed row 4 (first/mean exist, metric_summary.py:34), row 6 (use_dataset/use_model exist, sdk/run.py:693-699), row 8 (torch_watch.py:144), row 17 (row 'proposal' vs file 'done 2026-10-10'), row 19 (row 'done' vs file 'proposal'), the stale intro line, and the unlinked 28-measurements.md. The status-agreement check needs a fixed vocabulary in both the rows and the files' Status lines, which the draft's 'status class' glossed over. Size S -> M; now depends on F4 for row links.
- F11: dropped the draft's 'newer format is skipped' test; test_record_format_read.py:56, :84 and :109 already pin it. Added an unknown-entry-type fold test, the part of the contract nothing covers. Fixture moved under the existing tests/golden/ directory and loaded through tests/empty_storage.py instead of a new fixtures tree. Flagged that these are pinning tests and must be shown to fail under a deliberate break.
- F1: narrowed the 'banned claims' test to the two absolute phrasings. A broad 'no server / no database' ban would flag true sentences (reports.md:5-7, skill.py:14 / agent-skill.md:5, PRODUCT.md:24). Added a warning not to copy PRODUCT.md:24's 'hosted control plane' sentence into docs, given PRODUCT.md:51.
- F2 and F3: replaced string-absence tests that only restate a one-off edit ('does not say Plugin ecosystem: None', 'has a Sources section', 'says there is no importer') with two code-tied checks (registry.STORAGE_EXTRAS schemes and ENTRY_POINT_GROUP named in the comparison), in the style of test_docs_similar_statements.py. PRODUCT.md edits were put to the owner, who approved them (F2).
- F6: added the missed occurrences (:255 `exp create`, :1552 `exp diff`); dropped the install-duplication test; kept the stuck-formula and command-name tests.
- F4: confirmed by an independent read-only scan that ui.md:450 (:448 when drafted) is the only broken relative link in scope today, so the real-files test is red for exactly one reason; priority kept at P2 because F3, F6 and F8 rely on it.
- F12: marked '3.9 works' as a static read (no 3.8/3.9 interpreter here, CI runs one Python); the draft stated it as true today (the floor is now 3.10 for both packages). F14: fixed evidence (PRODUCT.md:51, not :50, is the hosted-claims line; sdk.md:111-114; plan 11 :11-12 and :63) and noted that torch watch() already exists.
- Evidence corrections throughout: vmn-vs-mlflow.md:112-113 (not :113), experiments.md:509-511 (not :510-511), packaging.md:188-198, test_workspace.py:32-35; the commit and tag counts (1,758 / 1,444 touching the exp packages / 1,319 conventional subjects / 39 tags) were re-measured, last at 59becdd5.
