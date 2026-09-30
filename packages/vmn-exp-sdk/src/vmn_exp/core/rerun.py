"""Pure helpers behind ``vmn-exp rerun``: what a run recorded, and what its
rerun is made of.

A rerun executes a run's recorded command against the run's own code. Its
record copies the original's code identity (so it shares the code object and
its ``<code_verstr>.rN`` name keeps that object alive through prune), links
back via ``rerun_of`` and gets a fresh log.

Signatures (the CLI builds on exactly these):

- ``rerun_blocker(meta, code_key=None) -> str | None`` — why *meta* can't be
  rerun; *code_key* is the object :func:`~vmn_exp.core.code_store.find_code_key`
  found for a ``from_snapshot`` record.
- ``recorded_invocation(run_state, log) -> Invocation | None``
- ``resolve_command(inv, override) -> (Invocation | None, error | None)``;
  *override* is ``args.run_cmd`` (None without ``--``, ``[]`` for a bare ``--``).
- ``rerun_template(meta, rerun_of, note, timestamp) -> dict`` for ``create_run``.
- ``code_verstr_of(meta) -> str`` — allocate the rerun under this.
- ``create_params(log) -> dict`` — the original ``create`` entry's params.
- ``repo_relative_cwd(cwd, root) -> str | None`` — POSIX, ``"."`` at *root*.
- ``remap_live_paths(argv, live_root, work_root) -> list``
- ``child_env(work_cwd, experiment_dir, sweep_params=None) -> dict`` for
  ``_Supervision(extra_env=)``; *experiment_dir* is the effective store root
  (``$VMN_EXPERIMENT_DIR`` if set, else the live repo root), None leaves it.

No ``version_stamp`` import: this module ships in vmn-exp-sdk.
"""
import collections
import json
import os
import shlex

from vmn_exp.core.provenance import no_code_reason

RUNNER_CLI = "exp run"
RUNNER_SDK = "sdk"

Invocation = collections.namedtuple("Invocation", "command cwd runner")

# The original's code identity, copied verbatim into the rerun's record.
CODE_IDENTITY_FIELDS = (
    "base_version", "base_commit", "branch", "remote", "app_name", "dirty_states",
    "has_working_tree_patch", "has_local_commits_patch", "has_untracked_files",
    "has_dep_patches", "diff_hash", "untracked_skipped", "changesets",
    "dep_base_commits", "code",
)
# Dirty states whose code lives in patches (a snapshot only has it in a code object).
_PATCHED_STATES = {"pending", "outgoing", "dirty_deps"}


def rerun_blocker(meta, code_key=None):
    """Why *meta*'s run can't be rerun, or None."""
    reason = no_code_reason(meta)
    if reason:
        return reason
    if _dirty_snapshot(meta) and not (meta.get("code") or code_key):
        return "recorded from a dirty exported snapshot whose code is not in the store"
    return None


def _dirty_snapshot(meta):
    return bool(meta.get("from_snapshot")) and bool(
        _PATCHED_STATES & set(meta.get("dirty_states") or ())
    )


def recorded_invocation(run_state, log):
    """The command the run executed: ``run_state.yml``'s, else its last ``run``
    log entry's; None for a run that never ran anything. Legacy records
    without ``runner`` were ``vmn-exp run``s."""
    if run_state and run_state.get("command"):
        return Invocation(
            list(run_state["command"]),
            run_state.get("cwd"),
            run_state.get("runner") or RUNNER_CLI,
        )
    for entry in reversed(log or ()):
        if entry.get("type") == "run" and entry.get("command"):
            return Invocation(list(entry["command"]), None, RUNNER_CLI)
    return None


def resolve_command(inv, override):
    """``(invocation to run, None)`` or ``(None, error message)``.

    An *override* replaces the command and keeps the recorded cwd. An SDK run
    recorded its script's argv, not the interpreter, so it needs one.
    """
    if override is not None:
        if not override:
            return None, "Empty command after `--`: give the command to run"
        return Invocation(list(override), inv.cwd if inv else None, RUNNER_CLI), None
    if inv is None:
        return None, "The run recorded no command: pass one after `--`"
    if inv.runner == RUNNER_SDK:
        hint = shlex.join(["python"] + list(inv.command))
        return None, (
            "An SDK run records its script's arguments, not the interpreter: "
            f"pass the command after `--`, e.g. `-- {hint}`"
        )
    return inv, None


def rerun_template(meta, rerun_of, note, timestamp):
    """The rerun's metadata minus the identity ``create_run`` stamps on it."""
    template = {k: meta[k] for k in CODE_IDENTITY_FIELDS if k in meta}
    template.update(rerun_of=rerun_of, note=note, timestamp=timestamp)
    return template


def code_verstr_of(meta):
    return meta.get("code_verstr") or meta["verstr"]


def create_params(log):
    """The params of the run's ``create`` entry (``-f`` file, sweep trial)."""
    for entry in log or ():
        if entry.get("type") == "create":
            return dict(entry.get("params") or {})
    return {}


def repo_relative_cwd(cwd, root):
    """*cwd* relative to *root* as a POSIX path, ``"."`` at the root; None
    without a root or outside it."""
    if not root:
        return None
    rel = os.path.relpath(os.path.realpath(cwd), os.path.realpath(root))
    if rel == os.pardir or rel.startswith(os.pardir + os.sep):
        return None
    return rel.replace(os.sep, "/")


def remap_live_paths(argv, live_root, work_root):
    """*argv* with absolute paths under *live_root* (whole arguments or the
    value of ``--opt=path``) moved under *work_root*."""
    return [_remap_arg(arg, live_root, work_root) for arg in argv]


def _remap_arg(arg, live_root, work_root):
    prefix, sep, value = arg.partition("=")
    if sep and not os.path.isabs(prefix):
        return prefix + sep + _remap_path(value, live_root, work_root)
    return _remap_path(arg, live_root, work_root)


def _remap_path(path, live_root, work_root):
    if not os.path.isabs(path):
        return path
    live_root = os.path.normpath(live_root)
    path = os.path.normpath(path)
    if path == live_root:
        return work_root
    if path.startswith(live_root + os.sep):
        return os.path.join(work_root, os.path.relpath(path, live_root))
    return path


def child_env(work_cwd, experiment_dir, sweep_params=None):
    """The rerun child's env overrides.

    ``VMN_RESUME_RUN_ID`` maps to None: ``_Supervision`` removes it. A sweep
    trial's params are re-exported, its trial identity is not — a rerun is
    not a trial.
    """
    env = {"VMN_WORKING_DIR": work_cwd, "VMN_RESUME_RUN_ID": None}
    if experiment_dir:
        env["VMN_EXPERIMENT_DIR"] = experiment_dir
    if sweep_params is not None:
        env["VMN_SWEEP_PARAMS"] = json.dumps(sweep_params)
    return env
