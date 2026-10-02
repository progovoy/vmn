# Working-state snapshots

`vmn snapshot` captures your exact working state (uncommitted changes,
unpushed commits, untracked files, across every dependency) as a deterministic
version you can list, diff, export and restore. No WIP commits, no stash
management. It is built into `vmn`.

> **Use it when:** you're hours into a refactor that half-works and want to try
> a different approach without losing this one. Committing pollutes history
> with work you may discard; `git stash` gives you an unnamed entry with no
> record of dependency state. A snapshot gives you a version string: try the
> other approach, and if it's worse, restore.
>
> **Also useful for:** sharing a bug that only reproduces with your local debug
> changes; saving your state before an agent edits the same files.

```sh
vmn snapshot create my_app --note "promising results"
# => 1.2.0-dev.a1b2c3d.e4f5g6h

vmn snapshot list my_app
vmn snapshot diff my_app -v 1.2.0-dev.a1b   # other side defaults to your working tree
vmn snapshot restore my_app --latest        # dirty work is auto-saved first
```

The app must already be stamped (`vmn stamp -r patch my_app` once). A clean
tree has nothing to save: `create` says so and exits 0. Snapshotting a state
that is already saved returns the same version (same verstr and timestamp, so
its `@N` stays put) and only updates `--note`/`--meta` when given. When
`vmn stamp` refuses because of uncommitted changes, its hint points here.

A tree with unpushed commits is based on its upstream commit: the dev verstr
names the upstream, and the local commits are carried as a patch replayed on
top, so the snapshot restores in any clone of the remote.

## Actions

`vmn snapshot [action] <app>`; `create` is the default.

| Action | What it does | Ref |
|---|---|---|
| `create` | Save the working state; prints the verstr as its last stdout line | — |
| `list` | Rows `[N] <verstr>  (2m ago) - note key=value…`, oldest first | — |
| `show` | The record's metadata and its patches | defaults to latest |
| `note` | Set the note (`--note`) | `-v` or `--latest` required |
| `diff` | Compare a snapshot with another tree | defaults to latest |
| `export` | Write the snapshot's tree as a directory or `.tar.gz` | defaults to latest |
| `restore` | Put the snapshot's tree back in this checkout | `-v` or `--latest` required |
| `delete` | Remove the record (and its code object unless something else uses it) | `-v` or `--latest` required |

A ref (`-v`) is a full verstr, a unique prefix, `@N` (the number `list` shows:
the storage index, whatever `--last`/`--filter` hide) or `latest`.

`list`, `show`, `diff` and `export` take no repo lock, so they never wait for,
or hold up, a `vmn stamp` in the same checkout.

### restore

The checkout is reset to the snapshot's base commit (detached, as `vmn goto`
leaves it), then its local commits, working-tree patch and untracked files are
applied. Each dependency is checked out at its recorded base (the commit it
sat at when the snapshot was taken, or its upstream when it had unpushed
commits — not necessarily the stamped one) and patched the same way. First, the work it replaces is
saved as a snapshot noted `auto-saved before restore` (unless it already is
the target), and the command that brings it back is printed:

```text
Current work saved as 1.2.0-dev.a1b2c3d.9f8e7d6 — restore it anytime with: vmn snapshot restore my_app -v 1.2.0-dev.a1b2c3d.9f8e7d6
```

The resets (of the app and of each dependency) delete untracked files, and
untracked files over the size caps (`VMN_SNAPSHOT_MAX_FILE_MB`, default 50;
`VMN_SNAPSHOT_MAX_TOTAL_MB`, default 200) cannot go into that safety snapshot.
Dependency untracked files are guarded by the same caps: a restore that would
lose such files, in the app or a dependency, is refused
and lists them: move them away, raise the caps, or pass `--force` to restore
anyway and lose them. (`create` also leaves over-cap files out, records them
as `untracked_skipped` and warns.)

> **Note:** unlike `vmn goto`, a restore does *not* clone a missing dependency;
> it warns and skips it. Deps are expected to be on disk already.

### diff

```sh
vmn snapshot diff my_app                         # latest snapshot vs the working tree
vmn snapshot diff my_app -v @2 --to @5           # two snapshots
vmn snapshot diff my_app -v @2 --to 1.2.0        # a snapshot vs a stamped version
vmn snapshot diff my_app --tool meld             # two directories in an external tool
```

`--to` is the current working state by default (or `current`), else a
snapshot ref or a stamped version. Both trees are materialized and compared
file by file; `--tool` (default: `git config diff.tool`) gets them as two
directories instead.

### export

```sh
vmn snapshot export my_app                    # latest -> ./<verstr>.tar.gz
vmn snapshot export my_app -v @3 -o wip.tgz
vmn snapshot export my_app --latest -o ./code # a plain directory
```

The tree is materialized from the local repo (from the record's remote when
the base commit is not local), with patches and deps applied, every `.git`
stripped, and a `vmn_metadata.yml` written at its root. A `.tar.gz`/`.tgz`
holds one `<verstr>/` directory. The output path is printed.

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

A snapshot is a thin record referencing a content-addressed *code object*:

```text
.vmn/store/snapshots/<app-key>/<verstr>/metadata.yml
    # verstr, base version and commit, timestamp, note, user_meta,
    # dirty states, dep changesets, dep_base_commits, diff_hash,
    # code_verstr, and code: <key>
.vmn/store/code/<app-key>/<code_verstr>.<diff hash>/
    # the code object: working_tree.patch, local_commits.patch,
    # untracked_files.tar.gz, deps/<dep>/..., metadata.yml written last
```

(`<app-key>` is the app name with `/` replaced by `-`.) Snapshots of
the same tree share one code object, and `delete` removes it only when nothing
else references it. Dependency state feeds into the content hash, so two
snapshots differing only inside a dep get different version strings; so do
snapshots whose deps sit at different commits. Every
storage directory carries a `.gitignore` of `*`.

## All flags

| Flag | Actions | Description |
|------|---------|-------------|
| `-v`, `--version` | show, note, diff, export, restore, delete | Snapshot ref: verstr, unique prefix, `@N` or `latest` |
| `--latest` | same | Use the most recent snapshot (wins over `-v`) |
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
| `--store`, `--local` | all | Snapshot store (see below; `--store` needs vmn-exp) |

## With vmn-exp installed

[vmn-exp](vmn-exp/experiments.md) (experiment tracking) builds on snapshots: an
experiment run is a snapshot plus an append-only metrics log, and runs share
the code objects above. Installing it adds:

- **A shared store**: `--store <uri>` > `VMN_EXPERIMENT_STORE` > conf
  `experiment.storage.uri` (`s3://`, `gs://`, `az://`, `file://`; see
  [Storage](vmn-exp/experiments.md#storage-local-s3-gcs-azure-plugins)) puts records in
  the store's `snapshots` subdir and code objects next to the runs', so
  teammates can list, diff, export and restore each other's snapshots.
  `--local` forces the local store; `VMN_EXP_OFFLINE=1` keeps snapshots local
  too. Without vmn-exp, `--store` fails with `remote snapshot stores need
  vmn-exp: pip install vmn-exp`.
- **`vmn goto -v <snapshot-verstr> <app>`** (a full verstr, not a prefix or
  `@N`) restores a snapshot. `vmn goto -v <dev-version>` and `vmn-exp restore`
  run this same restore (auto-save, size-cap refusal, `--force`), with the hint
  `vmn goto -v <saved> <app>`; see
  [Restore vs goto](vmn-exp/experiments.md#restore-vs-goto).

Use a plain snapshot to save and restore code state; use a vmn-exp run to
record a command's metrics and compare runs. `vmn-exp snapshot` is not a
command: it points you at `vmn snapshot`.
