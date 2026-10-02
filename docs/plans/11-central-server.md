# 11 — vmn-exp as a central server (on-prem and BYO-bucket SaaS)

Status: **design, not started**. Decisions agreed 2026-10-02:

- vmn-exp may run as a central server, installed on-prem or offered as SaaS.
- SaaS is **bring-your-own-bucket**: we host the control plane, the data stays in the
  customer's object store.
- A database is allowed **as a cache only**. Both SQLite (single node) and Postgres
  (multi-replica / SaaS) are supported behind one interface.
- No new package: `vmn-exp ui` grows into the server.
- Runs are **never** written through the server. HTTP ingest was considered and rejected
  (§9).
- The server **never issues storage credentials**. Jobs write with the storage access
  their environment already has, and storage is configured exactly as today (`--store` >
  `VMN_EXPERIMENT_STORE` > conf `experiment.storage.uri`). The server reads the store with
  its own access; it doesn't hand access out (§5).
- **Jobs never talk to the server.** No server URL, no vmn token, no HTTP from jobs. Writers
  leave small change-journal entries **in the store**, and the server reads them to learn
  what changed (§5.2).

This replaces the rule in `docs/plans/README.md` ("no server in the data path") with the
invariants in §2.

---

## 1. Goals and non-goals

### Goals

1. **Collaboration.** Shareable links, SSO, per-workspace roles, and later reports and
   comments. This is where W&B wins today.
2. **Speed at scale.** Cross-app and cross-workspace queries, and several server replicas
   sharing one warm cache, instead of a per-process SQLite file each.
3. **Freshness without listing everything.** The dashboard learns about a write within about
   a second, at the cost of one small listing per tick, however many runs the store holds.
4. **A SaaS business that passes enterprise security review.** The customer's bucket stays
   the system of record. We never proxy run data, never hold write access to runs, and
   never mint credentials for the customer's storage.

### Non-goals (this plan)

- Model serving, LLM tracing, reports UI. Reports and comments only get a storage layout
  here (§7.3); their UX is a separate plan.
- Changing how jobs reach storage. Who may write which prefix is the customer's IAM, set up
  as today (instance roles, k8s workload identity, keys in the environment, NFS ACLs).
- Replacing the files-only tier. `start_run()` with an `s3://` store and no server must keep
  working unchanged, forever.
- A per-run ACL model. Roles are per workspace (optionally per app, §6.2).
- Columnar metric storage. That's a separate plan (series compaction). This plan only makes
  sure the cache layer doesn't block it.

---

## 2. Invariants

Every design choice below must keep these. Each one gets a test or a review checklist item.

| # | Invariant | Consequence |
|---|---|---|
| I1 | **Storage is the source of truth.** | Every run, log, artifact, registry record, report and comment is a file in the store, in the documented record format. |
| I2 | **The cache is disposable.** | You can drop the database at any time; `vmn-exp ui cache rebuild` (or just a restart) recreates it from storage, with no loss. The existing `SCHEMA_VERSION` drop-and-rebuild rule (`core/index_store.py`) applies to Postgres too. |
| I3 | **Training never depends on the server.** | Jobs never contact the server: they don't know whether one exists. A server that's down, slow or misconfigured costs dashboard freshness, never a run, a metric or a second of training. |
| I4 | **Runs are written only by jobs, straight to storage.** | The server never writes run data: no HTTP ingest, no write proxy (§9). Run records are byte-identical with or without a server; journal entries (§5.2) live outside run records. The server's own writes are metadata edits through the existing functions (§7.1), and only when its storage access allows them. |
| I5 | **The server never trusts what a journal entry says about data.** | Journal entries (§5.2) only tell the server which record to re-read; they never carry rows or metrics into the cache. |
| I6 | **The server never issues storage credentials.** | No STS, downscoped tokens or SAS for jobs. Storage access for jobs is the customer's IAM. The server uses only its own access, to read and (optionally) edit metadata. |
| I7 | **Control-plane state is separate from cache.** | Users, orgs, roles, API tokens, workspace definitions and the audit log live in the DB and **must be backed up**. They're the only DB contents that aren't disposable. Nothing about a run lives there. |
| I8 | **The files-only tier stays complete.** | `vmn-exp ui` with no `--db`, no auth config and a local checkout behaves as it does today. |

---

## 3. Deployment tiers

| Tier | Who runs what | Cache | Auth (to vmn) | Job writes | Server's storage access |
|---|---|---|---|---|---|
| **Standalone** (today) | User runs `vmn-exp ui` on a laptop or a shared box | SQLite under `--data-dir` | none / one `--token` | As today | The user's own |
| **On-prem server** | Customer runs `vmn-exp ui --config server.yml` (Docker image / Helm chart), 1–N replicas | SQLite (1 replica) or Postgres (N) | OIDC SSO + API tokens | As today, with the job environment's own access | The server deployment's own identity (k8s service account, instance role, keys), granted by the customer |
| **SaaS (BYO bucket)** | We run the same server, multi-tenant; customers connect buckets via a cross-account role | Postgres, row-level isolation per org | OIDC SSO (our IdP + customer IdP federation) + API tokens | As today, with the job environment's own access | A customer-created role we assume: read-only, or read plus metadata edits (§6.3) |

Jobs are configured the same way in all three tiers. Pointing a server at a store needs no
change on the job side.

It's one codebase. SaaS is the on-prem server with `tenancy: multi` and an onboarding
flow (§6.3).

---

## 4. Architecture

```
                         ┌──────────────────────── vmn-exp ui (server) ─────────────────────┐
  browser ──HTTPS──────▶ │  API (FastAPI, existing routes)   auth (OIDC / tokens / roles)   │
                         │      │  reads                                                     │
                         │      ▼                                                            │
                         │  snapshot cache (in-memory, per replica, per generation)          │
                         │      ▲ load_since(gen)                                            │
                         │  CacheStore ◀── refresh workers (leader)                          │
                         │  (SQLite | Postgres)    │  each tick: list journal after last key │
                         └─────────────────────────┼─────────────────────────────────────────┘
                                                   │ list / read (+ metadata edits),
                                                   │ with the server's own access
  job (SDK / vmn-exp run) ─────────────────────────▼──────────▶ bucket (truth)
         writes with its environment's own access,        ├── experiments/<app>/<verstr>/…  (records)
         configured as today; no server involved          └── journal/<minute>/…  (change journal, §5.2)
```

### 4.1 What exists and is reused

| Piece | Today | Change |
|---|---|---|
| Incremental index | `core/index.py` `ExperimentIndex`, `core/index_sweep.py` `Sweep` (names-only listing, live set, `touch`) | Add `hint(key)` for targeted refresh, fed by the journal reader (§5.2) |
| Listing after a key | `storage/object_client.py` `_iter(prefix, delimiter, start_after)` (S3 `StartAfter`, GCS `start_offset`, Azure client-side skip) | Reused by the journal reader |
| Store layout | `subdir` (`experiments`/`snapshots`) plus reserved pseudo-apps (`core/reserved.py`) | Replaced by top-level areas, `journal/` among them ([14-store-layout.md](14-store-layout.md)) |
| Cache persistence | `core/index_store.py` `IndexStore` (SQLite, JSON blobs, `load`/`save`) | Extract a `CacheStore` protocol; add `PostgresStore` (§4.2) |
| Background refresh | `ui/refresher.py` `Refresher` (thread per watched index, I/O helper process) | Leader election in multi-replica mode; followers only load (§4.3) |
| UI read cache | `ui/index.py` `WorkspaceIndex` (`cache` table for versions) | Same table in `CacheStore` |
| Workspaces | `ui/workspaces.py` `WorkspaceManager` → `workspaces.yml` | Backed by the DB under `--db`; yml stays for standalone |
| Auth | `ui/server.py` single bearer token middleware, `ui/security.py` `RequestGuard` | Pluggable `Authenticator` + `Authorizer` (§6) |
| Mutations | `ui/jobs.py` runs CLI subprocesses in git workspaces | Store-workspace mutations call the git-free functions in process (§7.1) |
| Storage resolution | `core/storage_resolve.py`, `storage/open.py`, backends' default credential chains | **Unchanged.** `open_storage` wraps remote stores with the journal writer (§5.2). |

### 4.2 Cache layer: `CacheStore`

Extract from `IndexStore` the interface `ExperimentIndex` already uses, and add what
multi-replica needs:

```python
class CacheStore(Protocol):
    def load(self, scope) -> dict            # {key: record}  (existing)
    def save(self, scope, changed, removed, states=None) -> None   # existing; bumps generation
    def generation(self, scope) -> int       # new: monotonically increasing per scope
    def load_since(self, scope, generation) -> tuple[dict, set, int]   # new: (changed, removed, new_gen)
    def kv_get(self, scope, fingerprint) / kv_put(scope, fingerprint, payload)  # WorkspaceIndex.cache
```

`scope` = `(workspace_id, app)`. Today it's `app`, with one file per workspace or store
(`ui/index.py:_db_path`).

**SQLite** (`core/index_store.py`): add a `seq INTEGER` column to `exp_index` and
`exp_index_state`, plus a `deleted` tombstone table. `generation` = `max(seq)`. This is a
small, backwards-safe change: bump `SCHEMA_VERSION`, which already triggers a rebuild.

**Postgres** (new `vmn_exp/ui/cache_pg.py`, `vmn-exp[postgres]` extra, `psycopg[binary]>=3`):

```sql
CREATE TABLE vmn_cache_meta   (k text PRIMARY KEY, v text);              -- schema version
CREATE TABLE vmn_records (
  org_id   bigint NOT NULL, workspace_id bigint NOT NULL, app text NOT NULL, key text NOT NULL,
  data     jsonb  NOT NULL,           -- folded record minus run state (as today)
  seq      bigint NOT NULL,           -- from a per-scope sequence
  PRIMARY KEY (org_id, workspace_id, app, key));
CREATE TABLE vmn_run_states (... same key ..., data jsonb NOT NULL, seq bigint NOT NULL);
CREATE TABLE vmn_tombstones (... same key ..., seq bigint NOT NULL);
CREATE TABLE vmn_scope_gen   (org_id, workspace_id, app, gen bigint, PRIMARY KEY (...));
CREATE TABLE vmn_kv          (org_id, workspace_id, scope text, fingerprint text, payload jsonb, ...);
CREATE INDEX ON vmn_records (org_id, workspace_id, app, seq);
```

- A heartbeat writes only `vmn_run_states`, as today.
- `save` runs in one transaction: it upserts, bumps `vmn_scope_gen.gen`, stamps `seq`,
  then fires `NOTIFY vmn_gen, '<scope>'`, so followers wake up without polling.
- Tombstones are trimmed after 10 minutes. A follower whose generation is older
  than the trim horizon does a full `load`.
- Rows stay JSON. Phase 1 doesn't push queries down to SQL (§4.4).

Schema version mismatch → `TRUNCATE` the cache tables. **Never** truncate control-plane
tables (I7). They live in a separate set of tables with their own migrations (Alembic is
overkill; use numbered SQL files under `vmn_exp/ui/migrations/`, applied at startup with
an advisory lock held).

### 4.3 Multi-replica refresh

- In Postgres mode, each scope has **one refresh leader** per cluster, chosen by
  `pg_try_advisory_lock(hash(scope))`. The leader runs today's `Refresher` loop for that
  scope (listing, reading, folding) and `save`s.
- Every other replica is a **follower**. It keeps the in-memory `IndexSnapshot` the API
  reads, updates it via `load_since(gen)` on `LISTEN vmn_gen` (falling back to a 1s
  poll), and never lists the bucket.
- If the leader dies, its session drops, the lock frees, and another replica takes over on
  its next tick.
- Watching stays demand-driven, as today (`IDLE_SEC`): a replica that gets a request for a
  scope tries to become its leader. A scope nobody looks at costs nothing.
- In SQLite mode there's one replica, which is always the leader. That's today's behaviour.

`ExperimentIndex` needs a "follower" constructor that skips `_refresh_from_storage` and
applies `load_since` deltas to its `RowCache` and `IndexSnapshot`. That's the only change
inside the index.

### 4.4 Queries

- **Phase 1–4:** unchanged. The query language (`core/query.py`) runs in Python over the
  replica's in-memory snapshot. That's measured at ~ms at 100k runs per app, and it keeps
  one implementation for the CLI, the SDK and the server.
- **Phase 5 (cross-app search, very large apps):** compile the query AST to SQL over
  `jsonb`, as a second backend of `filter_rows`. The same query-language test corpus has to
  pass on both backends (a conformance test). SQLite keeps the Python path.

### 4.5 The server's data flow

```
        bucket (truth)                                    Postgres (cache + control plane)
 ┌──────────────────────────┐                      ┌────────────────────────────────────┐
 │ journal/<minute>/…       │──(1) LIST new keys──▶│                                    │
 │ experiments/<app>/<v>/…  │──(2) read changed ──▶│ (3) fold (existing code) →         │
 │                          │      files only      │     upsert vmn_records/run_states, │
 │                          │                      │     save journal cursor, bump gen, │
 │                          │                      │     NOTIFY                         │
 └──────────────────────────┘                      └──────────────┬─────────────────────┘
          ▲                                                      │ (4) load_since(gen)
          │ (6) logs/series/artifacts read on demand              ▼
          └──────────────────────────────── replicas: in-memory snapshot ──▶ (5) API / UI
```

1. The workspace's journal reader lists the journal after its saved cursor (§5.2) and hands
   each entry to its scope's leader (§4.3).
2. It reads only the changed files of those records, with the server's own storage access,
   resuming logs from the saved offsets (`core/index_logs.py`).
3. It folds them with the existing index code and, in **one transaction**, upserts
   `vmn_records`/`vmn_run_states`, saves the journal cursor (`vmn_journal_cursor`, cache
   state), bumps the scope generation and `NOTIFY`s.
4. Every replica, the leader included, applies the delta to its in-memory `IndexSnapshot`
   (`load_since`).
5. List, filter, sort, leaderboard, facets and columns are answered from that snapshot,
   never from the bucket.
6. Heavy data (full logs, metric series, artifacts, media, code) is **not** in Postgres. Run
   pages read it from the bucket on demand into each replica's bounded in-memory cache
   (`ui/readers/parsed_logs.py`), with series downsampled as today. The columnar series plan
   ([12-columnar-metrics.md](12-columnar-metrics.md)) makes these reads range reads of precomputed levels.

- **Cold start or wiped cache:** one full listing builds the cache (the existing worker-process
  cold load), the cursor is set to the journal's newest key, and from then on step 1 drives
  everything.
- **Server edits (§7.1):** written to the bucket through the same storage layer (so they're
  journaled like any write), then the server hints the record itself, so the editor sees
  the change on their next request.

---

## 5. Write path: unchanged, plus a change journal in the store

### 5.1 What a job does

Nothing changes in how a job finds or reaches storage, and a job never contacts the server:

```
start_run()                                   # store from --store > VMN_EXPERIMENT_STORE > conf, as today
  1. open the store with the backend's default credential chain (as today)
  2. claim, code object, logs, segments, artifacts (as today)
  3. after each write that changes what a reader sees, one tiny journal object
     in the same store (§5.2), best effort, never blocks
```

No server URL, no vmn token, no new settings. Every writer gets the journal, because it
lives in the storage layer: the SDK, `vmn-exp run`, `vmn-exp push`, `import-mlflow`,
registry actions, `vmn snapshot` with a store, and the server's own edits (§7.1).

### 5.2 The change journal

**Why.** The index already finds changes by listing (`core/index_sweep.py`). Running records
are cheap to watch, but **new** records and late writes to finished ones are only found by
listing the app's records, which is costly at 100k runs per app. That's why the server's
full sweep runs every 30s and new runs can take that long to appear. A journal gives the
server one small, ordered listing per tick instead.

**Layout: one journal per store, time first.** One literal prefix for the whole store, so a
single listing per tick covers every app and every kind of record, and one lifecycle rule
cleans it up:

```
<store>/journal/<YYYYMMDDHHMM>/<unix_ms>_<area>_<app-key>_<writer_id>_<seq>_<name>
```

- `area` is the kind of record (`runs`, `snapshots`, `code`, `registry`, `reports`,
  `comments`, …; see [14-store-layout.md](14-store-layout.md)); `name` is the record name
  (a verstr for runs).
- The key carries everything the server needs (each field percent-encoded, joined with `_`,
  `unix_ms` zero-padded to 13 digits so keys sort by time). The body is empty, so reading
  the journal costs LIST calls only, no GETs.
- Partitioned by UTC minute, so a listing touches at most the last few partitions (Azure has
  no server-side start-after, so it lists those partitions whole and skips client-side).
- Time first rather than app first: a store with 200 apps costs one listing per tick, not
  200. Entries for apps nobody is watching are skipped (their next watch starts with a
  reconcile listing).

**When writers append an entry** (at most one per record per write batch, never for a
heartbeat-only `run_state.yml` rewrite, since running records are watched anyway):
- record claimed (`create_exclusive`) or `metadata.yml` written or updated
- a log segment or log sync uploaded
- an artifact, image or table upload finished
- final `run_state.yml` (exit code)
- code object completed, record deleted (`prune`/`delete`)

**Where it's implemented.** `vmn_exp/storage/journal.py`: a `JournaledStorage` wrapper that
`open_storage` (`storage/open.py`) puts around every remote and `file://` store, calling the
inner backend first and then putting the journal object.

**The journal is required.** It's part of the storage format (bump `core/record_format.py`)
and of the storage plugin contract. There's no opt-out and no support for writers without
it: there are no old clients to keep. A journal put is retried like the data write it
follows (same backoff as log segments). If it still fails, the writer treats it as a
failed storage write: log syncs queue it with the segment for the next sync, final writes
follow the existing final-upload path (`VMN_EXP_FINAL_UPLOAD_TIMEOUT_SEC`). Cost: about one
extra PUT per write batch, roughly one per 30s per running run on S3, a few cents a month
per run that's running continuously.

**How the server reads it.** One **journal reader per workspace** (store), each tick:
1. List `journal/<minute>/` for the current and previous minutes, starting after
   `last_seen_key − skew_window` (default 5 min, so a writer whose clock is behind is still
   picked up), using `_iter(prefix, delimiter, start_after)`.
2. Skip keys already seen (kept for the skew window). Route each new key by `(area, app)` to
   that scope's index: `hint(name)` does `Sweep.touch` plus `track`, and loads the record if
   it's new. The scope's normal refresh then re-reads only what grew (`index_logs.py`
   offsets). Keys for scopes nobody watches are dropped.
3. If more than 10k new entries arrive in one tick for one scope (a bulk import, or abuse),
   that scope does a full listing instead.
4. The cursor (`last_seen_key`) is saved per workspace in the cache (`vmn_journal_cursor`).

The journal never puts data into the cache: it only names records to re-read (I5). Anyone
who can write the store can write journal entries, which only cause re-reads of that store.

**Reconcile listing (not a fallback).** A writer can crash after a data write and before its
journal put, and a writer whose clock is more than `skew_window` behind writes keys the
server has already passed. Neither leaves a journal entry the server will read, so the
server does a full listing **at startup and every `reconcile_sec`** (default 3600). That
replaces today's 30s full sweep and the rolling slices in `core/index_sweep.py`. With the
journal, the per-tick listing is the journal only, and running records' `run_state.yml`
(heartbeats aren't journaled).

**Cleanup.** Entries are only useful for minutes. The server never deletes, so:
- The onboarding snippets (§6.3) include one lifecycle rule expiring `<prefix>/journal/`
  objects after 2 days (S3 lifecycle prefix filter, GCS `matchesPrefix`, Azure lifecycle
  `prefixMatch`). Lifecycle rules match literal prefixes only, which is why the journal is
  one top-level folder.
- `vmn-exp prune` also deletes journal partitions older than 2 days, for stores without a
  lifecycle rule (local disk, NFS, MinIO without lifecycle).

**Standalone uses it too.** `vmn-exp ui --store s3://…` today reads the same journal, so new
runs show up within a second without a server deployment.

**Multi-replica.** One replica per workspace holds the journal-reader lock
(`pg_try_advisory_lock(hash(workspace))`) and relays hints to scope leaders on other replicas
with `NOTIFY vmn_hint, '<scope>|<name>'`; followers get the result through `load_since` (§4.3).

---

## 6. Identity, roles, tenancy

### 6.1 Authentication (to vmn, not to storage)

Replace the inline token middleware in `ui/server.py` with an `Authenticator` chain:

| Method | Use | Notes |
|---|---|---|
| Static `--token` / `VMN_UI_TOKEN` | standalone (existing) | Kept as is. It maps to an implicit admin principal. |
| OIDC (authorization code + PKCE) | browsers | Generic OIDC discovery (Okta, Entra ID, Google, Keycloak, Auth0). Session cookie (`HttpOnly`, `SameSite=Lax`, `Secure`). CSRF stays covered by `RequestGuard` (same-origin plus JSON content type). |
| API tokens | scripts and tools calling the server API (jobs don't need one) | `vmnx_<id>_<secret>`; only an argon2 hash is stored; scoped to org + workspaces + role; expiry; listed and revoked in the UI. `vmn-exp login --server <url>` runs the OIDC device flow and stores a token in `~/.config/vmn-exp/credentials` (mode 0600), for CLI commands that call the server API. |

None of these grant storage access. A job that has a vmn token but no storage access
can't record anything except offline.

### 6.2 Authorization

- **Model:** org → workspace → (optional) app.
- **Roles:**
  - `viewer`: reads.
  - `editor`: tag, note, archive, rewind; model register and alias.
  - `admin`: prune, delete, workspace config, members, tokens.
- **Assignment:** to users or to IdP groups (an OIDC `groups` claim mapping).

Enforcement points:
1. Every API route goes through a dependency `require(role, workspace, app)`. Routes
   already take a workspace name, so this is one decorator per router module.
2. Jobs (§7.1) run as the requesting principal; that principal is recorded in the audit log.

**The boundary, to state plainly in the docs:**
- vmn roles govern what people can see and do **through vmn**: the UI, the API and
  server-side edits.
- Who can **write runs**, and who can read the bucket directly, is entirely the customer's
  storage IAM, set up the way it's set up today.
- Recommended setup: humans get no direct bucket access and use the UI; jobs get write
  access through their compute identity.

**Audit log** (control-plane table `vmn_audit`): mutations, membership and token changes,
logins. Exportable as JSONL. In SaaS, optionally mirrored as a file into the customer bucket
under `<prefix>/.vmn-audit/` (only when the server's access includes that prefix).

### 6.3 SaaS tenancy and onboarding

- Every control-plane and cache row carries `org_id`. Postgres row-level security policies
  enforce it, using `SET app.org_id` per request in middleware, so a missed `WHERE` clause
  can't leak across orgs. Cache rows get the same policy.
- **Onboarding a bucket** (the UI wizard plus a generated CloudFormation / Terraform snippet):
  1. The customer creates role `vmn-exp-reader`, trusting our AWS account with
     `ExternalId = <org external id>` (the confused-deputy guard). They pick one of two
     permission sets, both generated by us:

     | Permission set | Grants | UI |
     |---|---|---|
     | **Read-only** (default) | `GetObject`, `ListBucket` on `<prefix>/` | Browsing, compare, charts, search; mutations are hidden (done with the CLI, under the customer's own access) |
     | **Read + edits** | the above, plus `PutObject` limited to the files server-side edits write (§7.1): `runs/*/*/metadata.yml`, `registry/`, `reports/`, `comments/`, the per-writer log segments of the server's own writer id under `runs/*/*/log/` (rewind markers), and `journal/` (so its edits show up like any writer's) | Tag, note, archive, rewind, model alias/register from the UI |

     **Deletes are never in either set.** `prune` and `delete` stay customer-run CLI actions
     (decision 3, §14).
  2. They paste the role ARN, bucket and prefix.
  3. The server validates with a probe: assume the role, list, read one record, and, for
     read + edits, a conditional write of a probe key under its own prefix. It shows
     which check failed, and also checks the role **can't** delete (expects `AccessDenied`).
  4. The snippet also sets the bucket lifecycle rule that expires `<prefix>/journal/` after 2
     days (§5.2), and bucket CORS for signed browser downloads (§7.2). The probe warns when
     the lifecycle rule is missing.
  - GCS and Azure: the same two sets, as a service-account grant (GCS) or a managed-identity
    role assignment (Azure) to our identity.
- The server only uses the permissions it can probe. A workspace's capabilities
  (`read`, `edit`) are stored with it, and the UI and API hide or refuse actions it lacks.
- **SSRF / abuse guard:** in SaaS, only `s3://`, `gs://` and `az://` workspace URIs are
  allowed. `endpoint_url` is allowed only for an approved allowlist; `file://` and plugin
  schemes are refused. Today `add_store` accepts any registered scheme; gate that behind
  `tenancy: multi`.
- **Data residency of the cache.** The SaaS cache holds **derived metadata** (row fields:
  params, metric summaries, tags, notes, status) in our Postgres. That *is* customer data
  leaving their account, in derived form. Be explicit:
  - Document exactly what's cached: rows and folded summaries. Logs, series, artifacts,
    media and code are never cached server-side beyond a bounded in-memory LRU (parsed
    logs, `ui/readers/parsed_logs.py`, already bounded at 64 MB).
  - Encrypt at rest with a per-org data key; region-pinned deployments.
  - On disconnect: purge the org's cache rows (I2 makes that safe).
  - **Enterprise option, "data-plane agent":** the customer runs the on-prem server in
    their VPC (cache plus bucket access). The SaaS control plane only does identity, roles
    and routing, and the browser is pointed at the agent. That's a later phase, but this
    design must not block it: keep the cache and storage reads behind interfaces that a
    remote agent can implement.

On-prem is the same, minus tenancy: the server runs with whatever identity the customer
deploys it with. It gets the same capability probe and the same "only what's granted" rule.

---

## 7. Server-side features this enables

### 7.1 Metadata edits on store workspaces

Today store workspaces are read-only and mutations are CLI subprocess jobs in git
checkouts (`ui/jobs.py`).

- For store workspaces whose capabilities include `edit`, add **in-process** job actions
  that call the existing git-free functions against the workspace storage, with the
  server's own access:
  - tag, note, archive and unarchive (`metadata.yml` via `update_metadata`)
  - rewind (a marker appended to the server writer's log, `core/rewind.py`)
  - model register, alias and deprecate (`registry/` area, `registry/*` code)
- **Not offered from the server:** prune and delete (they need delete permission, which the
  server never asks for), push, and git actions (stamp, goto, restore, rerun). Those stay
  CLI-only, under the user's own access. Git-workspace jobs on-prem keep working as today.
- They keep the `JobRunner` interface (job id, log, status) and the
  one-mutation-per-workspace serialization, and add a per-scope advisory lock in Postgres
  mode.

### 7.2 Large reads

Artifact, media and output-log downloads in a store workspace. Two options, chosen per
workspace (decision 2, §14):

- **Stream** through the server (today's behaviour). Simple, no CORS. In SaaS the bytes
  pass through us (read path only) and we pay the egress.
- **Signed redirect:** the server answers `302` to a presigned GET for that one object
  (GET only, ≤5 min). It's signed with the server's own read access, so it grants nothing
  the server doesn't already have, and nothing beyond one object for minutes. It needs
  bucket CORS for `fetch()`-based previews.

Series and small JSON stay server-side, as today.

### 7.3 Reports and comments

Designed in [13-reports-comments.md](13-reports-comments.md). They're records in their own
store areas (`reports/`, `comments/`; [14-store-layout.md](14-store-layout.md)), so they obey
I1, are journaled, and survive a cache drop. They're server-side writes, so they need the
`edit` capability; the read + edits permission set includes both areas.

### 7.4 Shareable links

The SPA routes already encode workspace, app, run and compare state. Two changes:
- Guarantee URL stability: version the query-string state, and keep old keys parseable.
- When an unauthenticated user opens a link, redirect them through OIDC back to the same URL.

---

## 8. Configuration

`vmn-exp ui --config server.yml`. Every key also has a flag or environment variable; the
existing flags keep working.

```yaml
server:
  host: 0.0.0.0
  port: 8265
  public_url: https://vmn.acme.com          # OIDC redirects, links
  tenancy: single                           # single | multi (SaaS)
db: postgresql://vmn@db/vmn                 # omitted → SQLite under data_dir
data_dir: /var/lib/vmn-exp
auth:
  static_token_env: VMN_UI_TOKEN            # optional, standalone-compatible
  oidc:
    issuer: https://acme.okta.com
    client_id: vmn-exp
    client_secret_env: VMN_OIDC_SECRET
    groups_claim: groups
  role_mappings:
    - {group: ml-admins, workspace: "*", role: admin}
    - {group: ml-team,   workspace: ml-team, role: editor}
workspaces:                                 # seeded at startup; editable in UI (DB-backed)
  - name: ml-team
    store: s3://acme-ml/vmn                 # read with the server's own identity
    downloads: stream                       # stream | redirect (§7.2)
    reconcile_sec: 3600                     # full listing interval (§5.2)
```

Job side: unchanged. Jobs need no server setting (§5.1).

Ops deliverables:
- Docker image (`python:3.13-slim`; a free-threaded `3.14t` variant per the existing GIL hint)
- Helm chart (Deployment ×N with a service account the customer binds to storage, a
  Postgres dependency or external DSN)
- `/healthz` (liveness) and `/readyz` (DB reachable and migrations applied)
- Prometheus `/metrics`: refresh lag per scope, journal lag and entries per tick, cache generation, request latency
  per route. The `tests/uiload` SLO probe reuses these.

---

## 9. Rejected: HTTP ingest / write proxy

Considered and rejected (2026-10-02). Don't reopen this without a concrete user who can't
be served by the alternatives below.

| Case it would serve | Already covered by |
|---|---|
| Compute that can reach the server but not the bucket | Record offline (`VMN_EXP_OFFLINE`), then `vmn-exp push` from a host that can reach the bucket |
| Jobs that shouldn't hold long-lived bucket credentials | The compute's own short-lived identity (instance roles, k8s workload identity), set up by the customer |
| Clients in other languages | The documented record format; they write files with their own storage access like the Python SDK does |
| A fresh cache | The change journal in the store (§5.2) |

Reasons against:
- It puts the server on the training critical path (against I3).
- It routes customer data through us, which breaks the BYO-bucket promise.
- It makes us scale ingest for bursty sweeps.
- It adds a second write path that would have to stay byte-identical forever.

The same reasoning rejected **issuing storage credentials to jobs** (I6): it would need the
server to hold the right to mint write access to every customer's bucket, adds the hardest
per-cloud code in the plan, and creates a mid-run failure mode (refresh failing). Jobs keep
using the access their environment already has.

---

## 10. Failure modes

| Failure | Effect | Behaviour |
|---|---|---|
| Server down or unreachable | Dashboard unavailable | Jobs are unaffected; they never contact the server (I3). On restart the startup reconcile listing catches up, then the journal resumes from the saved cursor. |
| Postgres down | API can't load new generations | Replicas keep serving their last in-memory snapshot (stale banner in the UI via an `X-Vmn-Stale` header). Leaders keep their own in-memory index. Control-plane writes and logins return 503. |
| Cache corrupt or schema mismatch | — | Truncate and rebuild from storage (I2); the first request per scope waits for the initial load, as today. |
| Leader replica crashes mid-refresh | Its transaction rolls back | Another replica takes the advisory lock; no partial generation is visible. |
| Writer crashed between a data write and its journal put | That change has no entry | Found by the next reconcile listing (≤ `reconcile_sec`). |
| Writer clock more than `skew_window` behind | Its entries sort before what the server already read | Found by the next reconcile listing; the journal lag metric shows it. |
| No lifecycle rule and no prune | Journal objects accumulate (empty, so only object count grows) | Onboarding check warns; `vmn-exp prune` trims. |
| Junk journal entries | — | Only trigger re-reads of that store; past 10k per tick the server falls back to a full listing (I5). |
| Leaked vmn API token | Attacker can use the UI/API per the token's role | No storage access. Revoke in the UI; the audit log shows its use. |
| Server's storage access revoked (SaaS role removed) | Refreshes fail | Workspace marked `disconnected`; cache rows kept for 7 days, then purged. |
| Server role lacks `edit` | — | Edit actions hidden in the UI and refused by the API (capability probe, §6.3). |
| Clock skew between job and server | — | Derived status already uses the store's write time (`observed_at`). |

---

## 11. Security checklist (review gate for each phase)

- [ ] No code path issues storage credentials (I6): a test asserts no route returns
      credential-shaped data, and a grep gate keeps STS `AssumeRole` calls only in the
      server's own role assumption (`ui/storage_access.py`).
- [ ] The generated SaaS permission sets contain no `Delete*`; the onboarding probe refuses
      a role that can delete.
- [ ] `ExternalId` required on every SaaS role assumption.
- [ ] RLS enabled and forced (`FORCE ROW LEVEL SECURITY`) on every org-scoped table; a test
      connects as the app role without `app.org_id` and gets zero rows.
- [ ] Token secrets hashed (argon2id); constant-time compare (reuse `bearer_matches`).
- [ ] Journal entries cannot change cache contents (I5 test: entries for records that didn't
      change leave the snapshot identical; entries for unknown verstrs load nothing that
      isn't in storage).
- [ ] Workspace URI allowlist in multi tenancy; `endpoint_url` allowlist.
- [ ] Signed redirects (when enabled): GET only, ≤5 min, one object,
      `response-content-disposition` set for non-image types.
- [ ] Existing `RequestGuard` behaviour kept for cookie-authenticated mutations.
- [ ] The audit log covers every mutation route (test: enumerate mutating routes from the
      FastAPI app and assert each emits an audit entry).

---

## 12. Implementation plan

TDD per CLAUDE.md: each step lists its tests first. Worktree splits are sized to ~200–300
lines per file. Exp-suite tests go in `packages/vmn-exp/tests/`. Postgres tests use a
Docker `postgres:16` fixture (the suites already require Docker), skipped when the
`postgres` extra isn't installed.

### Phase 0 — `CacheStore` extraction (no behaviour change)

1. **Tests:** the existing index tests, parameterized over a `CacheStore` fixture, plus new
   tests for `generation()` and `load_since()` on SQLite: changes, removals, tombstone
   trimming, and the full-load fallback past the horizon.
2. **Code:**
   - `core/index_store.py` → `CacheStore` protocol plus `SqliteStore` (keep the `IndexStore`
     name as an alias).
   - `seq` columns, tombstones, `SCHEMA_VERSION` bump.
   - `ui/index.py` `WorkspaceIndex` uses `kv_get`/`kv_put`.
3. **Done when:** both suites are green and the uiload smoke profile is unchanged.

### Phase 1 — Postgres cache and multi-replica

| Worktree | Tests first | Code |
|---|---|---|
| 1a `cache_pg` | contract tests from phase 0 run against Postgres; RLS-off single tenancy | `ui/cache_pg.py`, `ui/migrations/0001_cache.sql`, `vmn-exp[postgres]` extra |
| 1b follower index | follower snapshot equals leader snapshot after N random record changes (property test); follower never calls storage listing (spy) | `ExperimentIndex.follower(store, scope)`, delta application to `RowCache` |
| 1c leader election | two `Refresher`s on one DSN: exactly one lists; killing the leader's connection hands over within 2 ticks | `ui/refresher.py` advisory-lock leadership, `LISTEN/NOTIFY` wakeups |
| 1d config | `--config` parsing; flags override file; `db:` absent → SQLite | `ui/config.py`, `ui/cli.py` wiring; workspaces from DB when `db:` set (`WorkspaceManager` backend) |

**Done when:** the uiload harness runs with 3 replicas plus Postgres and meets the existing
SLOs (`tests/uiload/slo.py`), with a new profile `multi-replica`.

### Phase 2 — change journal and targeted refresh

| Worktree | Tests first | Code |
|---|---|---|
| 2a journal writer | each write kind in §5.2 puts exactly one entry (recording fake store); heartbeat-only writes put none; key encoding round-trips verstrs and writer ids with any allowed characters; a failing journal put is retried and then queued with the next log sync | `vmn_exp/storage/journal.py`, `storage/open.py` wrapping |
| 2b journal reader | entries after `last_seen − skew` are read once each and routed to the right `(area, app)` scope; 200 apps cost one listing per tick; a writer 4 min behind is picked up, 6 min behind is left to the reconcile listing; minute rollover; >10k entries → full listing; works on S3 (MinIO), GCS (fake) and Azure (Azurite) listing paths | `vmn_exp/core/journal_reader.py` (pure listing logic, used by the index) |
| 2c targeted refresh | `hint(key)` makes the next refresh re-read only that record (storage spy); an entry for an unchanged record does nothing (I5); a new verstr is loaded without a full listing | `ExperimentIndex.hint`, `Sweep` wiring, refresher reads the journal each tick |
| 2d e2e + prune | new-run-to-visible latency under 1.5s in the uiload harness with `reconcile_sec=3600`; per-tick LIST count doesn't grow with the number of finished runs; the full sweep and rolling slices are removed from `core/index_sweep.py`; `vmn-exp prune` deletes journal partitions older than 2 days | uiload profile `journal`; `cli/prune.py` |

### Phase 3 — authentication, roles and audit

| Worktree | Tests first | Code |
|---|---|---|
| 3a authenticators | static token unchanged; OIDC with a mock IdP (authlib test server or a minimal fake); API token create/verify/revoke/expire | `ui/auth/{static,oidc,tokens}.py`, control-plane migration `0002_identity.sql` |
| 3b authorizer | the route × role matrix generated from the FastAPI app: every route has a declared role, viewer can't mutate, editor can't change members | `ui/auth/authz.py`, `require()` dependency on each router |
| 3c login + audit | `vmn-exp login` device flow against a fake IdP writes a 0600 credentials file; every mutating route emits an audit entry | `vmn_exp/cli/login.py` (vmn-exp), `ui/audit.py` |
| 3d store edits | tag/note/archive/rewind/model actions on a store workspace via in-process jobs give the same results as the CLI on the same store; refused without the `edit` capability | `ui/jobs_store.py`, capability probe `ui/storage_access.py` (§7.1) |

### Phase 4 — SaaS tenancy and BYO-bucket onboarding

- **Tests:**
  - RLS isolation (two orgs, cross reads return nothing).
  - ExternalId enforcement.
  - The onboarding probe reports each failing check, detects read-only vs read + edits, and
    refuses a role that can delete.
  - Workspace URI allowlist.
  - Signed redirect for artifacts and media.
  - Disconnect purges the cache.
- **Code:**
  - `org_id` everywhere, RLS policies, org middleware.
  - `ui/onboarding.py` and generated IaC snippets for both permission sets (AWS first; GCS
    and Azure grants as docs snippets).
  - `ui/routes_media.py` redirects.
  - Purge job.

### Phase 5 — query pushdown

`core/query_sql.py` compiles the AST to Postgres `jsonb`. The conformance test runs the
whole query-language test corpus through both backends on the same rows. Cross-workspace
search endpoint `GET /api/v1/search?q=`.

### After each phase

Run `/simplify` on the change. Update the docs (§13). Run the full core and exp suites
once on master.

---

## 13. Docs to write or update

- `docs/vmn-exp/server.md` (new): tiers, `server.yml`, Postgres, replicas, OIDC, roles,
  tokens, audit, metrics, Helm, the server's storage identity.
- `docs/vmn-exp/byo-bucket.md` (new): onboarding, the two permission sets per cloud, the journal
  lifecycle rule, what the SaaS cache holds, the data-plane agent option, and a plain statement that jobs' storage
  access is the customer's IAM.
- `docs/vmn-exp/ui.md`: `--config`/`--db`, downloads stream vs redirect, `reconcile_sec`, journal lag metrics.
- `docs/vmn-exp/experiments.md`: the change journal (layout, when entries are written,
  lifecycle rule, prune trimming), required by the storage plugin contract; `vmn-exp login`. Job configuration unchanged.
- `docs/vmn-exp/vmn-vs-mlflow.md`: update the "Multi-user / permissions" row. "Remote
  logging over HTTP" stays **No**, by design, with a link to §9's reasoning.
- `docs/plans/README.md`: replace the "no server in the data path" rule with §2's
  invariants.
- CLAUDE.md: the command, environment variable and architecture notes.

---

## 14. Open decisions

1. **SaaS cache residency.** Is caching derived rows in our Postgres acceptable as the
   default (encrypted, region-pinned, purgeable), with the data-plane agent for customers
   who refuse? Recommended: yes.
2. **Downloads in SaaS:** stream through us, or signed redirects? Recommended: signed
   redirects (the data doesn't transit us, no egress bill), with stream as the fallback for
   buckets without CORS.
3. **Prune and delete stay CLI-only.** The server never asks for delete permission.
   Recommended: yes. Revisit only if customers ask for retention policies run from the UI.
4. **Per-app roles.** Ship per-workspace roles only (simpler), or per-app from the start?
   Recommended: per-workspace; add app scoping only if asked.
5. **Pricing hooks.** Seats vs tracked runs vs workspaces. It affects what the control plane
   must meter: workspaces, runs indexed and rows cached are all cheap to count.
