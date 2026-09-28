# vmn-exp model registry

The model registry links named, versioned model identifiers to the experiment runs and
artifact paths that produced them. It lives in the same storage root as experiment runs
(under the reserved pseudo-app `vmn-registry`) so no extra infrastructure is needed — the
same local directory or S3 bucket you already use for experiments holds the registry.

- [Concepts](#concepts)
- [Refs](#refs)
- [CLI](#cli)
- [SDK](#sdk)
- [UI](#ui)
- [Storage and scope](#storage-and-scope)
- [Prune protection](#prune-protection)
- [Clock skew and `--expect`](#clock-skew-and---expect)

---

## Concepts

**Model** — a named collection of versions.  Names use letters, digits, underscores, and
dots; no hyphens; no `.vN` suffix (that's reserved for the version record names).
Example: `bert_base`, `resnet50`, `fraud.detector`.

**Version** — an immutable record attached to a specific experiment run and (optionally)
an artifact path within that run.  Version numbers are assigned atomically in ascending
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
and never take the repo lock.  Pass `--dir`, `--bucket`, `--prefix`, `--endpoint-url` to
select a non-default storage root (same flags as `vmn-exp`).

### `vmn-exp model register <model> -v <run-ref>`

Register a new version of `<model>` pointing at the experiment run `<run-ref>`.

```sh
vmn-exp model register resnet50 -v 1.6.0-dev.a1b2c3d.e4f5g6h
vmn-exp model register resnet50 -v 1.6.0-dev.a1b2c3d.e4f5g6h --app my_app
vmn-exp model register resnet50 -v latest --artifact weights/model.pt --alias staging
vmn-exp model register resnet50 -v latest --description "fine-tuned on v2 data"
```

Flags:
- `-v` / `--version` (required): experiment run ref (verstr, `@N`, `--latest`)
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

List all model names in the registry.

```sh
vmn-exp model list
vmn-exp model list --json
```

### `vmn-exp model show <model>`

Show all versions and their current status and aliases.

```sh
vmn-exp model show resnet50
vmn-exp model show resnet50 --json
```

### `vmn-exp model resolve <ref>`

Print the resolved version metadata for a ref (useful in scripts).

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

Mark a version as deleted.  Aliases pointing to it are removed first (errors if
any alias would be left dangling — remove them explicitly beforehand, or use
`--force` to remove aliases automatically).

```sh
vmn-exp model delete resnet50 1
vmn-exp model delete resnet50 1 --force   # also removes aliases pointing at v1
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

The returned dict contains:
- `n`: version number (int)
- `run_ref`: `{"app": ..., "verstr": ...}`
- `artifact_path`: relative path within the run (may be absent)
- `description`: human-readable string (may be absent)
- `status`: `"active"`, `"deprecated"`, or `"deleted"`
- `aliases`: list of alias names currently pointing at this version
- `created`: ISO timestamp

### Downloading an artifact

```python
path = download_model("resnet50@production")               # returns local path
path = download_model("resnet50@production", dst="/tmp")   # copies to a dir
```

Local storage returns the on-disk path directly.  S3 storage downloads to a
temporary cache directory.

### Listing

```python
print(list_models())   # ["bert_base", "resnet50"]
```

### Storage override

All functions accept an optional `storage=` keyword for passing an explicit
storage object.  When omitted, storage is resolved from env / git checkout (same
as `start_run`).

---

## UI

The `vmn-exp ui` dashboard has a **Models** page listing all registered models and
their current aliases and statuses.  Clicking a model opens a detail page that
shows all versions with links to the originating experiment runs.

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

---

## Prune protection

`vmn-exp prune` (and `vmn-exp prune --query`) refuses to delete any run that has
at least one active (non-deleted) model version pointing to it, even with
`--force`.  To free storage, delete the model version first:

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
