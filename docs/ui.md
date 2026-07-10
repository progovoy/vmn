# vmn ui

`vmn ui` serves a web dashboard and REST API over your vmn repos and experiment
stores. Reads go straight to git tags and `.vmn/` files (or S3) — lock-free and
always consistent with the CLI. Mutations run as real `vmn` subprocesses.

## Install

The UI ships inside the wheel but pulls in a couple of extra runtime deps, so it
lives behind an extra:

```sh
pip install "vmn[ui]"
```

Without the extra, `vmn ui` prints an install hint and exits.

## Localhost

```sh
cd your-project
vmn ui                     # 127.0.0.1:8265, auto-attaches this repo, opens a browser
vmn ui --port 9000 --no-browser
```

The current repo becomes an implicit workspace. Open the printed URL.

## Workspaces

A **workspace** is an isolated source of data:

- a **git checkout** — its own working tree, `.vmn/`, lock, and derived index; or
- a read-only **S3** experiment bucket.

The server hosts many. Several git workspaces may be clones of the *same* remote
(e.g. one per branch or per user) — a stamp or restore in one never touches
another's working tree.

Register sources at startup:

```sh
vmn ui --data-dir /srv/vmn-ui \
       --repo /srv/checkouts/model-a \
       --repo /srv/checkouts/model-b \
       --s3-bucket team-experiments --s3-prefix ml --endpoint-url http://minio:9000
```

or at runtime via the API (`POST /api/v1/workspaces` with `{"name","path"}`).
The registry persists in `<data-dir>/workspaces.yml` (default `~/.vmn-ui`).

### S3-only (no git repo)

```sh
vmn ui --s3-bucket team-experiments --s3-prefix ml
```

Experiment browsing (leaderboards, run detail, artifacts) works with no local
checkout. Repo actions (stamp/goto) are naturally unavailable for S3 sources.

## Remote deployment

```sh
vmn ui --host 0.0.0.0 --port 8265 --token "$VMN_UI_TOKEN" --data-dir /srv/vmn-ui
```

- **Auth**: a single shared bearer token (`--token` or the `VMN_UI_TOKEN` env).
  Every `/api` request must send `Authorization: Bearer <token>`. Binding beyond
  localhost without a token logs a warning.
- **TLS & users**: put a reverse proxy (nginx/Caddy) in front — vmn does not
  terminate TLS or manage accounts.
- **`--read-only`**: disables all mutation endpoints (stamp/restore/goto/…),
  returning 403. Good for a shared read-only dashboard.

Example nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:8265;
    proxy_set_header Host $host;
}
```

## Actions

Mutations are asynchronous jobs:

1. `POST /api/v1/workspaces/{ws}/apps/{app}/actions/{stamp|restore|goto|release|prune|note}`
   with a JSON body → `202` + `{"id": ...}`.
2. `GET /api/v1/jobs/{id}` → status (`running`/`succeeded`/`failed`), exit code,
   and the captured log.

Each job runs `vmn <cmd>` as a subprocess in the workspace, so it acquires the
per-repo lock (serializing correctly against terminal use) and at most one
mutation runs per workspace at a time. Restores/gotos over a dirty tree
auto-snapshot your work first (the safety net) — the job log tells you the
recovery command.

## The index

By default the server keeps a small SQLite cache under `<data-dir>/index/` to
make leaderboards and the stamp tree instant over large repos. It is derived
from the source files and rebuilt on staleness (tag list / experiment-dir
mtimes) — delete it any time. `--no-index` reads directly.

## API

Full OpenAPI/Swagger docs at `/api/docs`. Everything is scoped by workspace:
`/api/v1/workspaces`, `.../apps`, `.../apps/{app}/experiments`,
`.../experiments/{verstr}`, `.../experiments-diff`, `.../versions`, `.../tree`,
`.../tree/root`, `.../deps`, `.../snapshots`, and `/api/v1/jobs/{id}`.
