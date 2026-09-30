# vmn-exp model registry

The model registry links named, versioned models and datasets to the
experiment runs and artifacts that produced them. It lives in the experiment
storage root you already use (under the reserved pseudo-app `vmn-registry`),
so it needs no extra infrastructure.

- [Concepts](#concepts)
- [Refs](#refs)
- [CLI](#cli)
- [SDK](#sdk)
- [Datasets](#datasets)
- [Using versions](#using-versions)
- [UI](#ui)
- [Storage and scope](#storage-and-scope)
- [Prune protection](#prune-protection)
- [Clock skew and `--expect`](#clock-skew-and---expect)

---

## Concepts

**Model**: a named collection of versions. Names use letters, digits, `_` and
`.`, don't start with `.`, contain no `-`, and don't end in `.v<digits>`
(reserved for version records). Examples: `bert_base`, `resnet50`,
`fraud.detector`.

**Kind**: every name is a `model` or a `dataset`. They share one namespace;
registering a name as the other kind is an error. Records without a kind are
models.

**Version**: an immutable record pointing at an experiment run and
(optionally) an artifact path in it. A *reference dataset* version has no run;
it records a `uri` and a `digest` instead. Numbers are assigned atomically from
1 and never reused, even after a delete.

**Alias**: a mutable pointer to a version number, for stages like `staging`,
`production`, `canary`. Aliases use letters, digits, `_`, `-` and `.`; `latest`
and all-digit names are reserved.

**Status**: `active`, `deprecated` (informational, still resolvable) or
`deleted` (hidden from default listings, not resolvable; the number stays
retired).

---

## Refs

Wherever the CLI or SDK takes a model reference:

| Ref | Resolves to |
|-----|-------------|
| `model` | Latest non-deleted version |
| `model@latest` | Same as bare name |
| `model@3` | Version 3 (error if deleted) |
| `model@alias` | The version the alias points at |

An unknown alias, a deleted or missing version, or a model with no
non-deleted versions raises `KeyError` (the CLI exits 1).

---

## CLI

`vmn-exp model <action>` is git-free: it reads and writes experiment storage
directly and never takes the repo lock. Every action takes `--dir`
(or `VMN_EXPERIMENT_DIR`), `--store <uri>` and the `--bucket`/`--prefix`/
`--endpoint-url` shorthand to pick the storage root, resolved like the rest of
`vmn-exp` ([Storage](experiments.md#storage-local-s3-gcs-azure-plugins)).

| Action | Usage | Notes |
|---|---|---|
| `register` | `register <model> (-v <run-ref> \| --kind dataset --uri <uri>)` | Prints `Registered <model> version N (...)` |
| `alias` | `alias <model> <alias> <N> [--expect <N\|none>]`, `alias <model> <alias> --remove` | `--expect` mismatch exits 1 |
| `list` | `list [--kind model\|dataset] [--json]` | Model and dataset names |
| `show` | `show <model> [--json]` | Kind, description, versions with status and aliases |
| `resolve` | `resolve <ref> [--json]` | Prints model, app, verstr, artifact, `uri` (artifact storage URI or dataset URI), digest |
| `deprecate` | `deprecate <model> <N>` | Still resolvable |
| `delete` | `delete <model> <N>` | Refused while an alias points at it |

### register

```sh
vmn-exp model register resnet50 -v 1.6.0-dev.a1b2c3d.e4f5g6h --app my_app
vmn-exp model register resnet50 -v latest --app my_app --artifact weights/model.pt --alias staging
vmn-exp model register resnet50 -v @3 --app my_app --description "fine-tuned on v2 data"
vmn-exp model register imagenet --kind dataset --uri /data/imagenet      # hashed
vmn-exp model register imagenet --kind dataset --uri s3://data/imagenet/ --digest sha256:ab12...
vmn-exp model register train_split --kind dataset -v latest --app prep --artifact data/train.parquet
```

| Flag | Description |
|---|---|
| `-v`, `--version` | Run ref: full verstr, unique prefix, `@N` or `latest`. Exactly one of `-v` and `--uri` |
| `--app` | The run's app. Required for any ref but a full verstr; pass it anyway, since a version recorded without an app cannot be downloaded |
| `--artifact` | Artifact path within the run |
| `--kind` | `model` (default) or `dataset` |
| `--uri` | A reference dataset's location (needs `--kind dataset`); a local file or directory is hashed ([Datasets](#datasets)). Registering a digest the dataset already has prints the existing version |
| `--digest` | Dataset digest `sha256:<hex>`; for a `-v` dataset it defaults to the digest the run logged for `--artifact` |
| `--description` | Human-readable description |
| `--alias` | Point this alias at the new version |

### alias, delete

```sh
vmn-exp model alias resnet50 production 3
vmn-exp model alias resnet50 production 4 --expect 3   # only if currently at 3
vmn-exp model alias resnet50 staging --remove
vmn-exp model delete resnet50 1
```

`--expect` takes a version number or `none` (the alias must not exist yet); see
[Clock skew](#clock-skew-and---expect). `delete` of a version that runs recorded
using ([Using versions](#using-versions)) succeeds but warns
`... was used by K runs`: their lineage still names it.

`resolve --json` prints `{model, n, app, verstr, artifact_path, artifact_uri,
kind, uri, digest}`.

---

## SDK

```python
from vmn_exp.sdk import (
    register_model, set_alias, remove_alias, get_model_version, list_models,
    download_model, register_dataset, get_dataset_version, use_model, use_dataset,
)
```

Every function takes an optional `storage=`; without it storage is resolved
like `start_run` (see [Storage and scope](#storage-and-scope)).

```python
with start_run("my_app") as run:
    run.log_artifact("weights.pt")
    meta = run.register_model("resnet50", artifact_path="weights.pt", alias="staging")
    meta["n"], meta["run_ref"]    # 1, {"app": "my_app", "verstr": "1.6.0-dev..."}

# after the run: a Run, or a verstr plus its app
register_model("resnet50", run=run, artifact_path="weights.pt")
register_model("resnet50", run="1.6.0-dev.a1b2c3d.e4f5g6h", app_name="my_app")

set_alias("resnet50", "production", 2)
set_alias("resnet50", "production", 3, expect=2)   # compare-and-swap; ValueError on mismatch
remove_alias("resnet50", "staging")

meta = get_model_version("resnet50@production")    # or "resnet50@2", "resnet50"
path = download_model("resnet50@production")       # local path
path = download_model("resnet50@production", dst="/tmp")   # copied into a dir
list_models()                                      # ["bert_base", "imagenet", "resnet50"]
```

`register_model(name, run=None, ...)` defaults `run` to the current run.
`get_model_version` returns the version record:

| Key | Value |
|---|---|
| `model`, `n` | Name and version number |
| `run_ref` | `{"app", "verstr"}` (absent for a reference dataset) |
| `artifact_path` | Path within the run (may be absent) |
| `uri`, `digest`, `size`, `files` | Dataset fields (may be absent) |
| `description`, `timestamp`, `format_version` | |

Status and aliases are not in it; read them from `vmn-exp model show --json`
(or `vmn_exp.registry.view.model_state`). `get_model_version` never records a
use.

`download_model` returns the on-disk path on local storage and downloads to a
temporary cache from a remote store. Inside an open run it records a use of
the version ([Using versions](#using-versions)); `record=False` opts out. A
reference dataset, or a version with no artifact path, raises `ValueError`.
`list_models()` lists both kinds; `vmn_exp.registry.store.list_models(storage,
kind="dataset")` filters.

---

## Datasets

Datasets are registry entries of kind `dataset`, with the same refs, aliases
and statuses as models.

**Reference mode** (the default) copies no bytes: the version records where the
data lives and its digest.

```python
from vmn_exp.sdk import register_dataset, get_dataset_version

register_dataset("imagenet", "/data/imagenet", alias="train")   # local dir: hashed
register_dataset("raw_logs", "s3://lake/logs/2026-09/", digest="sha256:ab12...")
meta = get_dataset_version("imagenet@train")
# {"model": "imagenet", "n": 1, "uri": "/data/imagenet", "digest": "sha256:...",
#  "size": 123456, "files": 42, ...}
```

A local file's digest is its `sha256:<hex>`; a directory's is the sha256 of a
manifest of every file below it, sorted by relative path
(`<relpath>\0<file sha256>\n` per file), so it depends on names and contents
only. Local paths are stored absolute. Remote URIs are not read: pass
`digest=` yourself, or none.

**Copied mode** points the version at an artifact of a data-prep run; the run
is then prune-protected and lists the dataset in its lineage `models`:

```python
with start_run("prep") as run:
    run.log_artifact("train.parquet", name="data/train.parquet")
    register_dataset("train_split", run=run, artifact_path="data/train.parquet")
```

Pass exactly one of `uri` or `artifact_path`. With `dedupe=True` (the default),
registering a digest the dataset already has returns that (newest,
non-deleted) version. `register_dataset` on a model name, and
`get_dataset_version` / `use_dataset` of a model, raise `ValueError`.

---

## Using versions

A run records the model and dataset versions it consumed:

```python
with start_run("serving") as run:
    meta = run.use_model("resnet50@production")   # returns the version record
    data = run.use_dataset("imagenet@train")
    path = download_model("resnet50@production")  # also records (record=True)
```

`use_model` / `use_dataset` also exist as module functions (`run=` defaults to
the current run; with no run open they only resolve). Each use writes:

- an `input` on the run named `<name>@<N>`, pinned to the resolved number
  (never the alias), with `kind` `model` or `dataset`. A run-backed version
  gets its artifact's `vmn://<app>/<verstr>/<path>` URI and digest (what
  `run.use_artifact` records, so lineage links the run to its producer); a
  reference dataset gets `vmn-registry://<name>@<N>`.
- a `use` entry in the registry record `<name>-uses` (never the model's own
  log): `{"type": "use", "version": N, "run": {"app", "verstr"}, "ts",
  "writer", "pos", "actor"}`. Best-effort: a failure is a warning.

A run records each version once. `get_model_version`, `get_dataset_version`
and `register_model` never record; `NoOpRun.use_*` (non-zero ranks, disabled
mode) only resolve.

### Lineage

Uses extend the [run lineage](sdk.md#lineage): from the consuming run, a used
run-backed version is an upstream link to its producer (any app) carrying
`model`, `version` and `kind`, and reference datasets are listed in
`datasets`. From the version,
`vmn_exp.registry.lineage.version_lineage(storage, name, n)` (also
`GET .../models/{name}/versions/{n}/lineage`) answers its producer run and
every consumer in `<name>-uses`, pruned ones marked `found: false`.

---

## UI

The `vmn-exp ui` **Models** page lists every model and dataset with a kind
badge (and a kind filter) and its aliases. A model's page shows its versions
linked to their runs, and a **lineage** card with the picked version's
producer and consumers. A **Register** button on a run page's Artifacts panel
registers a version from the browser. With `--read-only` the page is
read-only. The HTTP routes are in [ui.md](ui.md#model-registry-api).

---

## Storage and scope

One registry per storage root: models registered in a local `.vmn` directory
are not visible from a separate bucket root. The `vmn-registry` pseudo-app is
hidden from experiment app listings (`vmn-exp list`, the UI, `list_runs`).

Artifacts are **referenced, not copied**: a version stores the run ref and a
relative path; the bytes stay in the run's storage.

Records under `vmn-registry`: `<name>` (header: `kind`, `description`),
`<name>.v<N>` (one per version), `<name>-uses` (the usage log; model names
never contain `-`, so it cannot collide with a model).

---

## Prune protection

`vmn-exp prune` (including `--query`) refuses to delete a run that any
non-deleted version points at, even with `--force`; that includes a copied
dataset's data-prep run. Reference datasets have no run and protect nothing.
Runs that merely *used* a version are not protected; pruning one leaves its
`use` entry behind. To free a registered run, delete its versions first:

```sh
vmn-exp model delete resnet50 3
vmn-exp prune my_app -v 1.6.0-dev.a1b2c3d.e4f5g6h
```

---

## Clock skew and `--expect`

Alias moves resolve last-writer-wins by `(timestamp, writer_id,
position_in_log)`. When two hosts sharing a bucket move the same alias at
nearly the same time, the outcome is deterministic but may not be what the
second writer meant. `--expect` / `expect=` turns the move into a
compare-and-swap that fails unless the alias currently points at the expected
version (`none`: the alias must not exist):

```sh
vmn-exp model alias resnet50 production 4 --expect 3
```
