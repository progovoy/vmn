# Running `vmn-exp ui` as a central server

`vmn-exp ui` is also the team server. There is no separate package. This page
covers what changes when one `vmn-exp ui` process serves a team: the config
file, the cache, how the cache stays fresh, cache maintenance, sign-in, API
tokens and roles. For the flags, workspaces and HTTP API of a single-user
dashboard, see [ui.md](ui.md). For giving a server access to your bucket, see
[byo-bucket.md](byo-bucket.md).

## Ground rules

- **Storage is the source of truth.** Runs, logs, artifacts, registry records,
  reports and comments are files in the store. The server only reads them, and
  writes metadata edits when it has the access to (see
  [Edits on store workspaces](#edits-on-store-workspaces)).
- **The cache can be thrown away.** Delete it at any time and the server
  rebuilds it from storage, without a restart.
- **Jobs never talk to the server.** They write to the store with whatever
  storage access their environment already has, configured as usual
  (`--store` > `VMN_EXPERIMENT_STORE` > conf `experiment.storage.uri`). Jobs
  need no server URL and no token. If the server is down, the dashboard is
  unavailable and training is unaffected.
- **The server never issues storage credentials.** vmn roles control what
  people can do through the UI and API. Who can write runs, and who can read
  the bucket directly, is up to your storage IAM.

## Standalone vs configured

| Mode | Started with | Workspace registry | API tokens, OIDC, audit log |
|---|---|---|---|
| Standalone | `vmn-exp ui [--repo ...] [--store ...]` | `<data-dir>/workspaces.yml` | no (only a static `--token`) |
| Configured | `vmn-exp ui --config server.yml`, or `--db` / `VMN_UI_DB` | control-plane DB | yes |

The control-plane DB holds the workspace registry, API tokens, login sessions
and the audit log. Unlike the cache, it is not rebuilt from storage, so back it
up. `--db` accepts `sqlite:///<path>` or a Postgres DSN
(`postgresql://user@host/db`; `pip install "psycopg[binary]>=3"`). Without it,
a configured server keeps a SQLite DB in the data dir. On Postgres the numbered
migrations under `vmn_exp/ui/migrations/` are applied at startup, and the same
database also holds the shared cache of store workspaces (see
[Postgres and replicas](#postgres-and-replicas)).

## `server.yml`

```yaml
server:
  host: 0.0.0.0
  port: 8265
  public_url: https://vmn.example.com   # needed for OIDC (redirect URI)
  tenancy: single                       # single | multi (Postgres, SaaS)
  endpoint_allowlist: []                # store endpoint_urls allowed in multi tenancy
data_dir: /var/lib/vmn-exp              # default ~/.vmn-ui
db: sqlite:////var/lib/vmn-exp/control.db   # or postgresql://vmn@db/vmn; default: SQLite in data_dir
auth:
  static_token_env: VMN_UI_TOKEN        # env var holding the static token
  oidc:
    issuer: https://example.okta.com
    client_id: vmn-exp
    client_secret_env: VMN_OIDC_SECRET  # env var holding the client secret
    groups_claim: groups                # default "groups"
  role_mappings:
    - {group: ml-admins, workspace: "*", role: admin}
    - {group: ml-team,   workspace: ml-team, role: editor}
workspaces:                             # registered at startup if absent
  - name: ml-team
    store: s3://acme-ml/vmn
    downloads: stream                   # stream | redirect
    reconcile_sec: 3600                 # full listing interval
```

Unknown keys are an error. For each key the precedence is flag > environment
variable > file > default:

| Key | Flag | Environment |
|---|---|---|
| `server.host` / `server.port` | `--host` / `--port` | none |
| `server.public_url` | none | `VMN_UI_PUBLIC_URL` |
| `db` | `--db` | `VMN_UI_DB` |
| `data_dir` | `--data-dir` | `VMN_UI_DATA_DIR` |
| static token | `--token` | the variable named by `auth.static_token_env` (default `VMN_UI_TOKEN`) |

Workspaces in `workspaces:` are only added when no workspace has that name
yet, so changes made in the UI survive a restart. `--repo` and `--store` still
attach more workspaces.

`downloads: redirect` makes artifact, media and output-log downloads of a
store workspace answer `302` with a presigned GET for that one object, signed
with the server's own read access. The bucket then needs CORS for the
dashboard's origin (see [byo-bucket.md](byo-bucket.md#cors-for-redirect-downloads)).
`stream` (the default) passes the bytes through the server.

The server refuses to bind beyond localhost without a token unless
`--read-only` is given. This is the same rule as standalone mode.

## The cache

The cache is SQLite, one database file per workspace under
`<data_dir>/index/`. It holds the folded run rows (params, metric summaries,
tags, notes, status), the per-app listing state and the journal cursor. Logs,
series, artifacts, media and code are not cached. Run pages read them from
storage on demand. `--no-index` keeps the cache in memory only.

## Postgres and replicas

With `db: postgresql://...` store workspaces are cached in Postgres instead of
the per-workspace SQLite files, so several replicas can share one cache:

- Each workspace app has one refresh leader, chosen with a Postgres advisory
  lock. The leader lists and reads the store and saves into the cache; every
  other replica follows, applying the cache's changes without touching the
  store. When a leader dies its lock frees and another replica takes over (and
  reconciles fully first).
- A save sends `NOTIFY vmn_gen`; followers `LISTEN` and refresh at once,
  falling back to their once-a-second tick.
- `GET /api/v1/search` runs the query language as SQL over the synced rows.
  Queries that read `outputs` (not kept on the synced rows) are filtered in
  Python instead.
- Git workspaces keep their SQLite cache under `<data_dir>/index/`, per replica.

Server-side edits (rewind, notes) write log segments under the writer id
`vmn-server`, unless `VMN_WRITER_ID` names another one, which is what the
generated edit policy allows (see
[byo-bucket.md](byo-bucket.md#the-servers-two-permission-sets)).

### Tenancy

`server.tenancy: multi` (Postgres only) turns row-level security on at startup:
every control-plane and cache row carries an `org_id`, and each transaction is
bound to the requesting principal's org (`set_config('app.org_id', ..., true)`,
never for the whole session), so a missing `WHERE` cannot leak rows across
orgs. A principal with no org gets `403`. Store URIs are limited to `s3://`,
`gs://` and `az://`, and an `endpoint_url` must be in
`server.endpoint_allowlist`. Background refreshes use the store's own org.

## How the cache stays fresh

A watched app (one the dashboard has asked for in the last minute) is
refreshed by a background thread once a second. An app nobody looks at costs
nothing. The first request after a pause restarts its refresh.

**Store workspaces read the change journal.** Every writer that goes through
vmn's storage layer (the SDK, `vmn-exp run`, `push`, `import-mlflow`, registry
actions, `vmn snapshot` with a store, the server's own edits) puts one empty
object under `<store root>/journal/` after each write that changes what a
reader sees:

```
<root>/journal/<YYYYMMDDHHMM>/<unix_ms>_<area>_<app-key>_<writer_id>_<seq>_<name>
```

`area` is the record kind (`runs`, `snapshots`, `code`, `registry`,
`reports`, `comments`, ...), and `name` is the record (a verstr for runs).
Fields are percent-encoded. Heartbeat-only `run_state.yml` rewrites are not
journaled. A journal put that fails is retried and then kept queued for the
writer's next write, so it is never dropped silently.

Once a second, the server lists the journal's last few minute partitions,
starting 5 minutes before its cursor so that writers with a slow clock are
still picked up. That is one listing for the whole store, however many apps
it holds. Each new entry tells the matching watched app to re-read that one
record. Entries never carry data into the cache: they only name records to
re-read from storage. A scope with more than 10,000 new entries in one tick
does a full listing instead. The cursor is saved in the cache, so a restart
resumes where it stopped.

Two more checks catch what the journal can miss (a writer that crashed between
its data write and its journal put, a clock far behind, a hand-edited file):

- **Full listing** at startup and on a rebuild.
- **Rolling consistency check:** each tick, a slice of the known records'
  file signatures is compared with the cache, sized so that every record is
  covered once per `reconcile_sec` (default 3600). Changed records are re-read.
  Each one is counted as drift (`vmn_cache_drift_total`).

**Git workspaces** have no journal. They are refreshed by listing the
checkout's records, as before.

The journal is only useful for minutes. `vmn-exp prune` deletes journal
partitions older than 2 days. On object stores, add a lifecycle rule as well
(see [byo-bucket.md](byo-bucket.md#journal-lifecycle-rule)).

## Self-healing and resync

On every tick the server checks that its cache file is still the one it built:
not deleted, replaced, unreadable or of another schema version. If any of
these fails, it rebuilds that workspace's cache in the background. The rebuild
writes a new file and renames it into place, and requests keep being served
from the current snapshot until the switch.

You can also trigger it by hand:

| Where | Resync (re-check every record, re-read the changed ones) | Rebuild (drop the cache, rebuild from storage) |
|---|---|---|
| API | `POST /api/v1/workspaces/{ws}/cache/resync` | `POST /api/v1/workspaces/{ws}/cache/resync?full=1` |
| CLI | `vmn-exp ui cache resync [--workspace <name>]` | `vmn-exp ui cache rebuild [--workspace <name>]` |
| UI | **Resync** button on the workspace dashboard | **Rebuild** button |

Both POSTs answer `202` and need the `admin` role. The UI buttons only appear
for admins and show a progress line (`rebuilding: 41,000 / 100,000 records`).

`GET /api/v1/workspaces/{ws}/cache/status` (admin) returns `state`
(`idle`/`rebuilding`), `progress {done, total}`, `rebuilds`,
`last_rebuild_reason`, `drift`, `journal_lag_sec`, and per app the
`generation`, `records`, `drift` and `last_reconcile_at`. `GET /metrics`
(viewer) serves `vmn_cache_drift_total{workspace=...}` in Prometheus text
format.

The CLI takes the server address from `--config` (`server.host`/`port`, and
its token), or else from `--host`/`--port`/`--token`/`VMN_UI_TOKEN`. Without
`--workspace` it acts on every workspace. When no server answers, `rebuild`
deletes the workspace's cache file so that the next start rebuilds it, and
`resync` does nothing, because every start reconciles fully anyway.

## Authentication

Methods are tried in this order. With none configured, the API is open, which
is the standalone behaviour.

| Method | For | Notes |
|---|---|---|
| Static token (`--token`, or the env var named by `auth.static_token_env`) | standalone, scripts | `Authorization: Bearer <token>`; acts as `admin` in every workspace |
| OIDC (`auth.oidc`) | browsers | authorization-code flow against the issuer's discovery document. Routes: `/auth/login`, `/auth/callback` (the redirect URI is `<public_url>/auth/callback`), `POST /auth/logout`. The session cookie `vmn_session` is `HttpOnly`, `Secure`, `SameSite=Lax` and lasts 12 h |
| API tokens | scripts and CLI calls to the server API | `vmnx_<id>_<secret>` bearer tokens. Needs a control plane (`--config` or `--db`) |

Only a salted hash of each API token's secret is stored (scrypt, or PBKDF2
where scrypt is unavailable). Admins manage tokens through the API:

```
GET    /api/v1/tokens                       list (no secrets)
POST   /api/v1/tokens  {"name", "roles": {"<ws>|*": "<role>"}, "ttl_sec"?}
                                            -> {"token", "record"}; the secret is shown once
DELETE /api/v1/tokens/{id}                  revoke
```

`vmn-exp login --server <url>` runs the OIDC device flow through the server
(`/auth/device/start`, `/auth/device/token`) and stores the API token it gets
(valid 90 days) in `~/.config/vmn-exp/credentials`, mode 0600 (honours
`$XDG_CONFIG_HOME`). Jobs never need it.

None of these grant storage access.

## Roles

There are three roles per workspace, `viewer < editor < admin`:

- `viewer`: all reads.
- `editor`: tag, note, archive, rewind, model register/alias/deprecate, and
  creating, saving and publishing reports and comments.
- `admin`: prune, deleting reports, cache resync/rebuild, API tokens and the
  audit log.

A principal's role in a workspace is the strongest of its own entry for that
workspace, its `*` entry, and every `role_mappings` entry whose `group` is in
its OIDC groups claim. With authentication off, everything is allowed.

The audit log records mutations and logins. Admins page it with
`GET /api/v1/audit?offset=&limit=`, or download it as JSONL from
`GET /api/v1/audit/export`.

## Edits on store workspaces

A store workspace has no checkout to run `vmn` in, so the server performs its
metadata edits in-process against the store, with its own access: tag, note,
archive/unarchive, rewind, model register/alias/deprecate (plus reports and
comments, see [reports.md](reports.md)). Prune, delete, push and git actions
(stamp, goto, restore, rerun) are never offered from a store workspace. Run
them with the CLI under your own access.

Before the first edit, the server probes the store: a list of the `runs` area
for `read`, and a create-if-absent write of a probe key under
`<root>/server/probe/` for `edit`. The result is saved with the workspace.
Without `edit`, edit requests get `403`. Git workspaces keep running their
actions as `vmn` subprocesses in the checkout.
