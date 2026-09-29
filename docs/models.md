# vmn-exp model registry

The model registry links named, versioned model identifiers to the experiment runs and
artifact paths that produced them. It lives in the same storage root as experiment runs
(under the reserved pseudo-app `vmn-registry`) so no extra infrastructure is needed — the
same local directory or S3 bucket you already use for experiments holds the registry.

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

**Model** — a named collection of versions.  Names use letters, digits, underscores, and
dots; no hyphens; no `.vN` suffix (that's reserved for the version record names).
Example: `bert_base`, `resnet50`, `fraud.detector`.

**Kind** — every name is a `model` or a `dataset` (one namespace: a name is
one or the other, and registering it as the other kind is an error). Records
from before datasets existed are models.

**Version** — an immutable record attached to a specific experiment run and (optionally)
an artifact path within that run.  A *reference dataset* version has no run: it
records a `uri` plus a `digest` (and `size`/`files` for a local path) instead.  Version numbers are assigned atomically in ascending
order starting at 1; numbers are never reused, even after a version is deleted.

**Alias** — a mutable pointer to a version number.  Any string is a valid alias except
`latest` (which always resolves to the highest non-deleted version number).  Aliases are
useful for deployment stages: `staging`, `production`, `canary`.

**Status** — each version is `active`, `deprecated`, or `deleted`.  Deleted versions are
hidden from default listings and cannot be resolved by number or alias; the number is
retired permanently.  `deprecated` is informational — the version is still resolvable.

---

## Refs

Wherever the CLI or SDK accepts a model reference, four forms are valid:

| Ref | Resolves to |
|-----|-------------|
| `model` | Latest non-deleted version |
| `model@latest` | Same as bare name |
| `model@3` | Version number 3 (error if deleted) |
| `model@alias` | Version the alias currently points to |

If `model` has no non-deleted versions, bare `model` and `model@latest` raise a
`KeyError`.

---

## CLI

All `vmn-exp model` sub-commands are git-free: they read/write experiment storage directly
and never take the repo lock.  Pass `--dir`, `--store <uri>` (or the `--bucket`/`--prefix`/`--endpoint-url` shorthand) to
select a non-default storage root (same flags as `vmn-exp`).

### `vmn-exp model register <model> (-v <run-ref> | --kind dataset --uri <uri>)`

Register a new version of `<model>` pointing at the experiment run `<run-ref>`,
or (for a reference dataset) at `<uri>`.

```sh
vmn-exp model register resnet50 -v 1.6.0-dev.a1b2c3d.e4f5g6h
vmn-exp model register resnet50 -v 1.6.0-dev.a1b2c3d.e4f5g6h --app my_app
vmn-exp model register resnet50 -v latest --artifact weights/model.pt --alias staging
vmn-exp model register resnet50 -v latest --description "fine-tuned on v2 data"
vmn-exp model register imagenet --kind dataset --uri /data/imagenet      # hashed
vmn-exp model register imagenet --kind dataset --uri s3://data/imagenet/ --digest sha256:ab12...
vmn-exp model register train_split --kind dataset -v latest --app prep --artifact data/train.parquet
```

Flags:
- `-v` / `--version`: experiment run ref (verstr, `@N`, `--latest`); exactly one
  of `-v` and `--uri` is required
- `--kind`: `model` (default) or `dataset`
- `--uri`: a reference dataset's location (needs `--kind dataset`). A local file
  or directory is hashed (see [Datasets](#datasets)); a remote URI keeps
  `--digest`. Registering a digest the dataset already has prints the existing
  version instead of adding one.
- `--digest`: the dataset digest (`sha256:<hex>`); for `-v` datasets it defaults
  to the digest the run logged for `--artifact`
- `--app`: app name; inferred from storage when omitted
- `--artifact`: relative artifact path within the run
- `--description`: human-readable description
- `--alias`: immediately point this alias at the new version

### `vmn-exp model alias <model> <alias> <version-number>`

Point `<alias>` at `<version-number>`.

```sh
vmn-exp model alias resnet50 production 3
vmn-exp model alias resnet50 production 4 --expect 3   # only if currently at 3
```

`--expect` takes a version number or `none` (meaning "alias must be absent").  A
mismatch exits non-zero — use this to guard against concurrent alias moves.

### `vmn-exp model list`

List all model (and dataset) names in the registry; `--kind model|dataset`
lists one kind.

```sh
vmn-exp model list
vmn-exp model list --json
vmn-exp model list --kind dataset
```

### `vmn-exp model show <model>`

Show all versions and their current status and aliases.

```sh
vmn-exp model show resnet50
vmn-exp model show resnet50 --json
```

### `vmn-exp model resolve <ref>`

Print the resolved version metadata for a ref (useful in scripts): app, verstr,
artifact, and a dataset's `uri`/`digest`; `--json` adds `kind`.

```sh
vmn-exp model resolve resnet50@production
vmn-exp model resolve "resnet50@latest"
```

### `vmn-exp model deprecate <model> <version-number>`

Mark a version as deprecated.  It remains resolvable.

```sh
vmn-exp model deprecate resnet50 1
```

### `vmn-exp model delete <model> <version-number>`

Mark a version as deleted.  Refused (exit 1) while any alias still points at
it — remove those aliases first (`vmn-exp model alias <model> <alias> --remove`).
Deleting a version that runs recorded using (see [Using versions](#using-versions))
succeeds but warns `... was used by K runs`: their logs still name it.

```sh
vmn-exp model alias resnet50 staging --remove
vmn-exp model delete resnet50 1
```

A version that is protected by the registry prune guard (i.e., the run that
produced it is still referenced by an active version) cannot be deleted via
`vmn-exp prune --force`; you must call `vmn-exp model delete` first.

---

## SDK

```python
from vmn_exp.sdk import (
    start_run,
    register_model,
    set_alias,
    remove_alias,
    get_model_version,
    list_models,
    download_model,
    register_dataset,
    get_dataset_version,
    use_model,
    use_dataset,
)
```

### Registering during a run

```python
with start_run("my_app") as run:
    # ... training ...
    run.log_artifact("weights.pt")

    # register_model on the run object resolves app + verstr automatically
    meta = run.register_model("resnet50", artifact_path="weights.pt", alias="staging")
    print(meta["n"])          # version number, e.g. 1
    print(meta["run_ref"])    # {"app": "my_app", "verstr": "1.6.0-dev.a1b2c3d..."}
```

### Registering after a run

```python
meta = register_model("resnet50", run=run, artifact_path="weights.pt")
# or by verstr:
meta = register_model("resnet50", run="1.6.0-dev.a1b2c3d.e4f5g6h", app_name="my_app")
```

### Aliases

```python
set_alias("resnet50", "production", 2)
set_alias("resnet50", "production", 3, expect=2)   # CAS-style guard
remove_alias("resnet50", "staging")
```

### Resolving a ref

```python
meta = get_model_version("resnet50@production")
meta = get_model_version("resnet50@2")
meta = get_model_version("resnet50")     # latest
```

The returned dict is the raw version record:
- `model`: the name
- `n`: version number (int)
- `run_ref`: `{"app": ..., "verstr": ...}` (absent for a reference dataset)
- `artifact_path`: relative path within the run (may be absent)
- `uri`, `digest`, `size`, `files`: dataset fields (may be absent)
- `description`: human-readable string (may be absent)
- `timestamp`: ISO timestamp of registration
- `format_version`: the record format

Status and aliases are not part of it — read them from `vmn-exp model show
<model> --json` (or `vmn_exp.registry.view.model_state`).
`get_model_version` never records a use, even inside a run.

### Downloading an artifact

```python
path = download_model("resnet50@production")               # returns local path
path = download_model("resnet50@production", dst="/tmp")   # copies to a dir
```

Local storage returns the on-disk path directly.  S3 storage downloads to a
temporary cache directory.  Inside an open run (`current_run()`) the download is
recorded as a use of that version (see [Using versions](#using-versions));
`record=False` opts out.  A reference dataset has nothing stored and raises
`ValueError`.

### Listing

```python
print(list_models())   # ["bert_base", "imagenet", "resnet50"] — models and datasets
```

`vmn_exp.registry.store.list_models(storage, kind="dataset")` filters by kind.

### Storage override

All functions accept an optional `storage=` keyword for passing an explicit
storage object.  When omitted, storage is resolved from env / git checkout (same
as `start_run`).

---

## Datasets

Datasets are registry entries of kind `dataset`, in the same namespace and with
the same refs, aliases and statuses as models.

**Reference mode** (the default) copies no bytes: the version records where the
data lives and a digest of it.

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
only. Local paths are stored absolute. Remote URIs are not read: pass `digest=`
yourself, or none.

**Copied mode** stores the bytes as an artifact of a data-prep run and points
the version at it — the run is then prune-protected and shows the dataset in
its lineage `models`:

```python
with start_run("prep") as run:
    run.log_artifact("train.parquet", name="data/train.parquet")
    register_dataset("train_split", run=run, artifact_path="data/train.parquet")
```

Pass exactly one of `uri` or `artifact_path`. With `dedupe=True` (the default)
registering a digest the dataset already has returns that (newest, non-deleted)
version instead of a new one. `register_dataset` on a model name, and
`get_dataset_version` / `use_dataset` of a model, raise `ValueError`.

---

## Using versions

A run records the model and dataset versions it consumed:

```python
from vmn_exp.sdk import start_run, download_model

with start_run("serving") as run:
    meta = run.use_model("resnet50@production")   # version metadata
    data = run.use_dataset("imagenet@train")
    path = download_model("resnet50@production")  # also records (record=True)
```

`use_model` / `use_dataset` also exist as module functions (`run=` defaults to
the current run; with no run open they only resolve). Each use writes:

- an `input` entry on the run named `<name>@<N>` — pinned to the resolved
  number, never the alias, so using `m@3` and later `m@4` keeps both. A version
  backed by a run artifact gets that artifact's `vmn://<app>/<verstr>/<path>`
  URI and digest (exactly what `run.use_artifact` records, so lineage links the
  run to its producer); a reference dataset gets `vmn-registry://<name>@<N>`.
  Its `kind` is `model` or `dataset`.
- a `use` entry in the registry record `<name>-uses` (not the model's own log,
  so the model's audit is untouched):
  `{"type": "use", "version": N, "run": {"app", "verstr"}, "ts", "writer", "pos", "actor"}`.
  This write is best-effort — a failure is a warning, never an exception.

A run records each version once. `get_model_version`, `get_dataset_version`
and `register_model` never record. On a non-zero rank, `NoOpRun.use_model` /
`use_dataset` resolve and record nothing.

### Lineage

Uses extend the run lineage ([sdk.md](sdk.md#lineage)) rather than adding a
graph of their own:

- From the consuming run (`get_lineage`, `vmn-exp lineage`, the run page's
  lineage card): a used run-backed version is an upstream link to its producer
  run, in any app, carrying `model`, `version` and `kind`; reference datasets
  are listed in `datasets` (`{model, version, kind, input, digest, found}`).
- From the version (`vmn_exp.registry.lineage.version_lineage(storage, name, n)`,
  `GET .../models/{name}/versions/{n}/lineage`, the model page's lineage card):
  `{model, version, kind, status, producer, consumers}` — the run it was
  registered from (None for a reference dataset) and every run recorded in its
  `<name>-uses` record, each marked `found: false` once pruned.

---

## UI

The `vmn-exp ui` dashboard has a **Models** page listing all registered models and
datasets, each with a kind badge and its current aliases (a kind filter narrows
it; API `?kind=model|dataset`).  Clicking one opens a detail page that shows all
versions with links to the originating experiment runs, and a **lineage** card
with the picked version's producer run and the runs that used it.

A **Register** button on the Artifacts panel of any run detail page lets you
register a new model version directly from the UI without leaving the browser.

The Models page and its API are read-only when `vmn-exp ui --read-only` is set.

---

## Storage and scope

The registry uses the same storage root as experiments.  One registry per storage
root: models registered in a local `.vmn` directory are not visible to a separate
S3 bucket root.  The pseudo-app `vmn-registry` is hidden from all experiment app
listings (`vmn-exp list`, the UI apps dropdown, `list_runs`).

Artifact files are **referenced, not copied**: the registry stores the run ref
and a relative artifact path; the actual bytes live in the experiment run's
storage directory.  Deleting a run that has a registered model version is blocked
by the prune guard.

Record layout under `vmn-registry`: `<name>` (header: `kind`, `description`),
`<name>.v<N>` (one per version), `<name>-uses` (the usage log; model names never
contain `-`, so it cannot collide with a model).

---

## Prune protection

`vmn-exp prune` (and `vmn-exp prune --query`) refuses to delete any run that has
at least one active (non-deleted) model version pointing to it, even with
`--force` — including a copied dataset's data-prep run.  Reference datasets have
no run and protect nothing.  Runs that merely *used* a version are not
protected: pruning one leaves its `use` entry behind.  To free storage, delete the model version first:

```sh
vmn-exp model delete resnet50 3
vmn-exp prune my_app -v 1.6.0-dev.a1b2c3d.e4f5g6h
```

---

## Clock skew and `--expect`

Alias moves are resolved by a last-writer-wins rule that uses `(timestamp,
writer_id, position_in_log)` as a tiebreaker.  In a shared-S3 setup where two
hosts move the same alias near-simultaneously, the outcome is deterministic but
may not match the intent of the second writer.  Use `--expect` / `expect=` to
turn the move into a compare-and-swap: the operation fails if the alias is not
currently pointing at the expected version.

```sh
vmn-exp model alias resnet50 production 4 --expect 3
```

The `--expect none` form asserts that the alias does not yet exist.
