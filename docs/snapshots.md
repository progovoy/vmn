# Working-state snapshots

`vmn snapshot` captures your exact working state — uncommitted changes,
unpushed commits, untracked files, across every dependency — as a
deterministic version you can list, diff, export, and restore. No WIP commits,
no stash management. It is built into `vmn`; `vmn-exp` is only needed for a
remote snapshot store and for `vmn goto -v <snapshot>`.

> **Use it when:** you're hours into a refactor that half-works and want to try
> a different approach without losing this one. Committing pollutes history
> with work you may discard; `git stash` gives you an unnamed entry with no
> record of dependency state. A snapshot gives you a version string — try the
> other approach, and if it's worse, restore.
>
> **Also useful for:** sharing a bug that only reproduces with your local debug
> changes; saving your state before an agent edits the same files.

```sh
vmn snapshot create my_app --note "promising results"
# => 1.2.0-dev.a1b2c3d.e4f5g6h

vmn snapshot list my_app
vmn snapshot diff my_app -v 1.2.0-dev.a1b   # second side defaults to your working tree
vmn snapshot restore my_app --latest        # dirty work is auto-saved first
```

The app must already be stamped (`vmn stamp -r patch my_app` once). A clean
tree has nothing to save: `create` says so and exits 0. Snapshotting a state
that is already saved returns the same version (same verstr, same timestamp, so
its `@N` stays put) and only updates `--note`/`--meta` when given.

When `vmn stamp` refuses because of uncommitted changes, its hint points here:
`vmn snapshot create <app>` saves the work without committing it.

## Actions

`vmn snapshot [action] <app>`; `create` is the default action.

| Action | What it does | Ref |
|---|---|---|
| `create` | Save the working state; prints the verstr as its last stdout line | — |
| `list` | Rows `[N] <verstr>  (2m ago) - note key=value…`, oldest first | — |
| `show` | The record's metadata and its patches (`--json` for JSON) | defaults to latest |
| `note` | Set the note (`--note`) | `-v` or `--latest` required |
| `diff` | Compare a snapshot with another tree | defaults to latest |
| `export` | Write the snapshot's tree as a directory or `.tar.gz` | defaults to latest |
| `restore` | Put the snapshot's tree back in this checkout | `-v` or `--latest` required |
| `delete` | Remove the record (and its code object unless something else uses it) | `-v` or `--latest` required |

A ref (`-v`) is a full verstr, a unique prefix, `@N` (the number `list` shows —
the storage index, whatever `--last`/`--filter` hide), or `latest`.

`list`, `show`, `diff` and `export` take no repo lock, so they never wait for —
or hold up — a `vmn stamp` or `vmn-exp run` in the same checkout.

### restore

The checkout is reset to the snapshot's base commit (detached, as `vmn goto`
leaves it), then its local commits, working-tree patch and untracked files are
applied, and the same for each dependency. Before that, the work it replaces is
saved as a snapshot noted `auto-saved before restore` (unless it already is the
target), and the command that brings it back is printed:

```text
Current work saved as 1.2.0-dev.a1b2c3d.9f8e7d6 — restore it anytime with: vmn snapshot restore my_app -v 1.2.0-dev.a1b2c3d.9f8e7d6
```

The resets (of the app and of each dependency) delete untracked files, and
untracked files over the size caps
(`VMN_SNAPSHOT_MAX_FILE_MB`, default 50, `VMN_SNAPSHOT_MAX_TOTAL_MB`, default
200) cannot go into that safety snapshot. When a restore would lose such
files, in the app or a dependency, it is refused and lists them; move them away, raise the caps, or pass
`--force` to restore anyway and lose them.

> **Note:** unlike `vmn goto`, a restore does *not* clone a missing dependency
> — it warns and skips it. Deps are expected to be on disk already.

With `vmn-exp` installed, `vmn goto -v <snapshot-verstr> <app>` restores a
snapshot too (it takes a full verstr, not a prefix or `@N`), through the same
lookup as experiment runs. `vmn goto -v <dev-version>` and `vmn-exp restore`
run this same restore — auto-save, size-cap refusal and `--force` — and their
hint names `vmn goto -v <saved> <app>`; see
[Restore vs goto](experiments.md#restore-vs-goto).

### diff

```sh
vmn snapshot diff my_app                         # latest snapshot vs the working tree
vmn snapshot diff my_app -v @2 --to @5           # two snapshots
vmn snapshot diff my_app -v @2 --to 1.2.0        # a snapshot vs a stamped version
vmn snapshot diff my_app --tool meld             # two directories in an external tool
```

The other side (`--to`) is the current working state by default (or
`current`), else a snapshot ref or a stamped version. Both trees are
materialized and compared file by file; `--tool` (default: `git config
diff.tool`) gets them as two directories instead.

### export

```sh
vmn snapshot export my_app                    # latest -> ./<verstr>.tar.gz
vmn snapshot export my_app -v @3 -o wip.tgz
vmn snapshot export my_app --latest -o ./code # a plain directory
```

The tree is materialized from the local repo (the record's remote when the
base commit is not local), with patches and deps applied, every `.git`
stripped, and a `vmn_metadata.yml` written at its root. A `.tar.gz`/`.tgz`
output holds one `<verstr>/` directory. The output path is printed.

### list, show, note, delete

```sh
vmn snapshot create my_app --note "lr sweep base" --meta owner=ana --meta ticket=ML-42
vmn snapshot create my_app --meta-file meta.yml       # a YAML mapping; --meta wins on a key
vmn snapshot list my_app --last 5 --filter owner=ana  # --verbose: full ISO timestamps
vmn snapshot list my_app --json                       # rows with their index
vmn snapshot show my_app -v @3 --json                 # {"metadata", "patches"}
vmn snapshot note my_app -v @3 --note "keep: best so far"
vmn snapshot delete my_app -v @1
```

## Where snapshots live

A snapshot is a thin record that references a shared *code object*:

```text
.vmn/<app>/snapshots/<verstr>/metadata.yml
    # verstr, base version and commit, timestamp, note, user_meta,
    # dirty states, dep changesets, diff_hash, code_verstr, and code: <key>
.vmn/vmn-code/<app>/experiments/<code_verstr>.<diff hash>/
    # the code object: working_tree.patch, local_commits.patch,
    # untracked_files.tar.gz, deps/<dep>/..., metadata.yml written last
```

Code objects are content-addressed and shared with experiment runs, so a
snapshot of a tree a run already recorded (or vice versa) stores no new
patches. `delete` removes the code object only when no other snapshot and no
run references it. Dependency state feeds into the content hash, so two
snapshots differing only inside a dep get different version strings. Every
storage directory carries a `.gitignore` of `*`.

### A shared store (needs vmn-exp)

With `vmn-exp` installed, snapshots go to the experiment store when one is
configured: `--store <uri>` > `VMN_EXPERIMENT_STORE` > conf
`experiment.storage.uri` (any [store URI](experiments.md#storage-local-s3-gcs-azure-plugins):
`s3://`, `gs://`, `az://`, `file://`; the `VMN_EXPERIMENT_BUCKET` shorthand
works too). Records go in the store's `snapshots`
subdir, code objects next to the runs', so teammates can list, diff, export and
restore each other's snapshots.

- `--local` uses the local store even when one is configured.
- `VMN_EXP_OFFLINE=1` keeps snapshots local too (see
  [Offline recording](experiments.md#offline-recording-and-push)).
- Without `vmn-exp`, `--store` fails with `remote snapshot stores need vmn-exp:
  pip install vmn-exp`.

## Snapshot vs. experiment — which do I want?

An experiment run is a snapshot plus an append-only metrics log. Use a plain
snapshot to save or restore code state; use an experiment when you want to
track and compare runs.

| | `vmn snapshot` | `vmn-exp` |
|:--|:--|:--|
| Captures code state (tracked + untracked + deps) | ✅ | ✅ |
| Metrics / params / notes | a note and `--meta` pairs | ✅ append-only log |
| Run a command, record its outcome | ❌ | ✅ (`vmn-exp run`) |
| Compare across runs | `diff` | diff + metric deltas + `compare` |
| Needs | `vmn` | `vmn-exp` |
| Typical use | saving WIP before a risky change | tracking and comparing runs |

`vmn-exp snapshot` is not a command: it points you at `vmn snapshot`.

## All flags

| Flag | Actions | Description |
|------|---------|-------------|
| `-v`, `--version` | show, note, diff, export, restore, delete | Snapshot ref: verstr, unique prefix, `@N` or `latest` |
| `--latest` | same | Use the most recent snapshot |
| `--note` | create, note | A description note |
| `--meta key=value` | create | Metadata pair (repeatable) |
| `--meta-file` | create | YAML mapping of metadata pairs |
| `--filter key=value` | list | Keep rows whose metadata matches (repeatable) |
| `--last N` | list | Only the N most recent snapshots |
| `--verbose` | list | Full ISO timestamps |
| `--json` | list, show | Print JSON |
| `--to` | diff | The other side: `current` (default), a snapshot ref, or a stamped version |
| `--tool` | diff | External diff tool (default: `git config diff.tool`) |
| `-o`, `--output` | export | Output directory or `.tar.gz`/`.tgz` (default: `<verstr>.tar.gz`) |
| `--force` | restore | Restore even if untracked files over the size caps would be deleted |
| `--store` | all | Snapshot store URI (needs vmn-exp) |
| `--local` | all | Use the local store even if one is configured |
