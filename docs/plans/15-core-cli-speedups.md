# 15 — Core CLI speedups (Python only)

Status: **proposal 2026-10-04, not started.** Three independent changes to cut the wall time
of every `vmn` command. No native code; [16-native-code.md](16-native-code.md) covers why.

Paths are under `packages/vmn/src/version_stamp/` unless noted.

---

## 1. Baseline

Measured on this repo (263 tags), macOS, warm cache:

| Command | Wall |
|---|---|
| `vmn --version` | ~0.34 s |
| `vmn show vmn` | 0.38–0.50 s |

`vmn show vmn` breakdown (`python -X importtime`, `cProfile`, `GIT_TRACE2_PERF`):

| Cost | Time | Cause |
|---|---|---|
| Imports of `version_stamp.cli.entry` | ~160 ms | `questionary` + `prompt_toolkit` ~39 ms, GitPython ~51 ms, `yaml` ~8 ms, `jinja2` ~7 ms |
| `git` subprocesses | ~130 ms | 12 sequential `git` processes |
| vmn's own logic | a few ms | YAML already uses `CSafeLoader` (`core/utils.py:15`) |

Target after all three steps: `vmn show` ≈ 150–200 ms.

How to re-measure (record before/after numbers in each PR):

```sh
python -X importtime -c "import version_stamp.cli.entry" 2>&1 | sort -t'|' -k2 -n | tail
GIT_TRACE2_PERF=/tmp/gp.log vmn show vmn >/dev/null; grep -c '| exit ' /tmp/gp.log
for i in 1 2 3; do /usr/bin/time -p vmn show vmn 2>&1 >/dev/null | grep real; done
```

---

## 2. Step 1: lazy-load the config TUI (~40 ms, small diff)

### Today

`cli/config_tui.py:9` imports `questionary` at module level, and three modules import
`config_tui` eagerly:

- `cli/entry.py:22`: `from version_stamp.cli.config_tui import handle_config`
- `cli/commands.py:10`: same re-export
- `cli/config_gen.py:6` and `cli/worktree_freeze.py:4` import helpers from it (conf
  load/seed functions, not the TUI)

So every command pays for `questionary` + `prompt_toolkit`.

### Change

- Move `import questionary` from module level into the functions in `config_tui.py` that
  prompt (57 call sites in one file; a single `_q()` accessor or a function-local import in
  each interactive entry point).
- Alternative, if the helpers used by `config_gen`/`worktree_freeze` are better off
  elsewhere: move them out of `config_tui.py` into a small non-interactive module (for example
  `cli/config_io.py`), and have `entry.py` dispatch `vmn config` with a lazy
  `import version_stamp.cli.config_tui`. Choose whichever is the smaller diff.
- Drop the `# noqa: F401` re-exports in `entry.py`/`commands.py` if nothing resolves
  `handle_config` through them (check the action-dispatch table in `entry.py` first).

### Tests (core suite, write first)

- `tests/test_import_cost.py::test_show_does_not_import_questionary`: in a subprocess, import
  `version_stamp.cli.entry`, run the `show` path on a fixture repo, and assert
  `"questionary" not in sys.modules` and `"prompt_toolkit" not in sys.modules`.
- Existing `tests/test_config.py` tests mock `questionary` via `import questionary as q` +
  monkeypatching module attributes. That keeps working with function-local imports (they
  resolve the same module object). Run them unchanged; if any break, stop and ask (TDD rule:
  no test edits to force green).

### Risk

Low. The only behaviour change is when the import happens.

---

## 3. Step 2: read tag messages in bulk (fewer git round trips)

### Today

`backends/git_tag_parse.py:22` `_parse_vmn_tags` loops over tag names and calls
`parse_tag_message` per tag. Per tag it goes through GitPython: `get_tag_object_from_tag_name`,
`tag_obj.object` (message, `tagged_date`), `tag_obj.commit` (`author.name` check). The comment
at line 68 notes each access re-resolves the ref. GitPython serves these from its
`cat-file --batch` process, so the cost is per-object round trips plus Python parsing, not
one process per tag. It grows linearly with the tags a command touches:

- `get_all_commit_tags` (`backends/git_tags.py:240`): `git tag --points-at`, then one parse per tag
- `get_all_brother_tags` (`git_tags.py:249`): `changeset` + the above, called from
  `get_all_commit_tags_log_impl` and `get_tag_version_info`
- `_get_shallow_first_reachable_vmn_stamp_tag_list` (`git_tags.py:121`): lists `<app>_*` and
  resolves candidates one by one

### Change

Add one bulk reader that returns, for a ref pattern or a `--points-at <sha>`, everything
`parse_tag_message` needs in one `git for-each-ref` call:

```sh
git for-each-ref --format='%(refname:strip=2)%00%(objecttype)%00%(*objectname)%00%(*authorname)%00%(taggerdate:unix)%00%(contents)%00%00' \
    [--points-at <sha>] 'refs/tags/<prefix>_*'
```

- `%(*objectname)` / `%(*authorname)` dereference the annotated tag to its commit, which
  replaces the `tag_obj.commit` + `author.name != VMN_USER_NAME` check.
- `%(taggerdate:unix)` replaces `tag_data.tagged_date` (used for sorting in
  `_sorted_tag_names_from_ver_infos`, `git_tags.py:62`).
- `%(contents)` is the full tag message for `yaml_safe_load`.
- NUL separators, plus a double-NUL record terminator because messages contain newlines.
- Lightweight tags (`objecttype == commit`) keep today's non-vmn handling.

`_parse_vmn_tags(tag_names)` becomes "bulk read, then parse each record". `parse_tag_message`
stays for single-tag callers and for the 0.3.9 compat path
(`compat/tag_format_039.py`, `parse_automatic_tag_message`), which keeps going through the
existing code.

### The coupling to watch

`ver_info` dicts carry GitPython objects: `"tag_object"` and `"commit_object"`. Consumers
outside the parser (18 references):

- `git_tags.py:67-70`: filters on `tag_object is not None`, returns `tag_object.name`
- `git_tags.py:223-227`: `commit_object` / `tag_object` truthiness
- `backends/local_file.py:154,188`: builds `ver_info` with both set to `None`
- the publisher/stamping code reading `commit_object` (grep `commit_object` before starting)

For step 2, keep the keys and build the objects lazily: either a tiny value object exposing
only what consumers read (`.name`, `.hexsha`, truthiness), or resolve the GitPython object
only when a consumer touches it. Don't change what consumers see in this step. Step 3 removes
the GitPython types.

### Tests (write first)

- Unit test for the record parser on a captured `for-each-ref` output: a multi-line YAML
  message, a message with text before the YAML document, a lightweight tag, a tag whose commit
  author is not vmn, and a non-UTF-8 byte in the message.
- Fixture-repo test: `get_all_commit_tags(sha)` on a commit carrying several brother tags
  (root app + services) returns the same `{tag: ver_info}` as today.
- Call-count test: with `GIT_TRACE2` (or a counting wrapper around `self._be.git`), resolving
  N brother tags issues O(1) git commands, not O(N).
- The existing core suite stays green unchanged. It already covers shallow clones, 0.3.9
  tags and root apps.

### Risk

Medium. Tag-message parsing is the core data path. Gate on the full core suite, including
the shallow-clone and old-format tests.

---

## 4. Step 3: drop GitPython for direct subprocess calls (~50 ms import, large diff)

### Today

`git.Repo` is the backend object itself (`backends/git.py:168`, `backends/factory.py`), not a
helper in two files. Surface in use (`grep -rhoE '_be\.[a-z_]+'`), about 40 distinct
attributes:

- Command passthrough, easy to port: `git.execute` (7), `git.rev_parse`, `git.branch`,
  `git.tag`, `git.log`, `git.for_each_ref`, `git.rm`, `git.reset`, `git.status`, `git.diff`,
  `git.config`, `git.checkout`, `git.ls_tree`, `git.format_patch`,
  `git.set_persistent_git_options`
- Object model, needs replacements: `head.commit` (5), `active_branch.commit`,
  `head.is_detached`, `iter_commits` (2), `tag`, `tags`, `refs`, `commit`, `create_tag`,
  `delete_tag`, `config_reader`, `is_dirty`
- Index API: `index.add/remove/commit/checkout`
- Repo discovery: `git.Repo(path, search_parent_directories=True)` and
  `git.exc.InvalidGitRepositoryError` (`backends/git.py:190`, `factory.py:19`),
  `git.Repo.clone_from` (`git_ops.py:259`), `git.exc.GitCommandError` (`git_ops.py:24`,
  `git_history.py:266`)
- `ver_info["tag_object"]` / `["commit_object"]` (§3)

`core/git_cmd.py` (`run_git`, `git_ok`, `git_stdout`) is already the plain-subprocess layer
used by islands and dev versions. Build on it.

### Change, in slices (each its own PR, each green on the core suite)

1. **Repo discovery + errors**: `git rev-parse --show-toplevel --git-common-dir` replaces
   `Repo(search_parent_directories=True)`. A local `GitCommandError`-equivalent carries
   stderr (keep the stderr-only message behaviour of `git_ops.py:21`).
2. **Command passthrough**: a thin `Git` shim whose `__getattr__` maps `git.<cmd>(*args)` to
   `run_git([cmd.replace('_','-'), *args])` with GitPython's return/raise semantics (stripped
   stdout, raise on non-zero). This ports the ~15 passthrough calls with no call-site edits.
3. **Refs and commits**: `head.commit` / `active_branch` / `is_detached` / `tags` / `refs` →
   `rev-parse`, `symbolic-ref`, `for-each-ref`. `iter_commits` → `git log --format=...`
   (step 2's NUL-record parser). Replace `tag_object`/`commit_object` with small dataclasses
   holding what consumers read.
4. **Writes**: `index.add/remove/commit`, `create_tag`, `delete_tag` → `git add`, `git rm`,
   `git commit`, `git tag -a -F -`. Watch author/committer identity (`VMN_USER_NAME`) and
   tag-message encoding.
5. **Remove the dependency** from `packages/vmn/pyproject.toml` once
   `grep -rn 'import git\b' packages/vmn/src` is empty. Check `packages/vmn-exp*` for
   transitive reliance on GitPython through vmn (it should go through `version_stamp.api`
   only).

### Tests (write first, per slice)

- Per slice, a behaviour test on a fixture repo for the ported operation (discovery from a
  subdir and from a linked worktree; detached HEAD; tag create/delete round trip with vmn
  identity; commit of `.vmn/` files).
- Final slice: `test_vmn_does_not_import_gitpython`, the same subprocess pattern as step 1's
  test, asserting `"git" not in sys.modules` after a `show`/`stamp` path.

### Risk and go/no-go

High effort, the most touched lines, and the smallest win (~50 ms). Do it only after steps
1–2 land and the re-measured numbers show GitPython's import as the largest remaining cost.
Slices 1–2 are worth doing on their own even if the rest is shelved.

---

## 5. Order and splitting

- Step 1 and step 2 are independent: two parallel worktrees, each with its own red-green cycle.
- Step 3 starts after step 2 (it reuses the bulk parser and replaces the object keys step 2
  preserved). One worktree per slice, in order.
- Each PR records before/after timings from §1 in its description.
