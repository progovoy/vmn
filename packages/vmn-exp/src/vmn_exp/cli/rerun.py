"""``vmn-exp rerun <app> -v <ref> [-- <cmd>]``: run a run's recorded command
again, against the run's own code, as a new run linked by ``rerun_of``.

The code is restored strictly into a throwaway workspace beside the repo
(:mod:`vmn_exp.cli.rerun_workdir`); the live checkout is never touched. The
new record copies the original's code identity instead of re-snapshotting the
workspace (:mod:`vmn_exp.core.rerun`), so it shares the original's code object
and, allocated under the same code verstr, keeps it alive through prune.
Nothing is created when the run can't be rerun faithfully. Like ``run``, the
repo lock is held only until the record is claimed.
"""
import os
from dataclasses import dataclass
from typing import Optional

from vmn_exp.cli import rerun_report as report
from vmn_exp.cli.rerun_workdir import exit_on_termination, plan_workdir, prepare_workdir
from vmn_exp.cli.rewind import _ref
from vmn_exp.cli.run import _Supervision, _detect_python_exe
from vmn_exp.core import rerun as core
from vmn_exp.core.app_conf import experiment_conf
from vmn_exp.core.code_store import (
    code_app, code_key, find_code_key, store_code, stored_code,
)
from vmn_exp.core.env import capture_env_safe, should_capture
from vmn_exp.core.fork import resolve_run
from vmn_exp.core.status import load_run_state
from vmn_exp.core.writer import create_run
from vmn_exp.snapshot import _patch_summary
from version_stamp.api import VMN_LOGGER, now_iso


@dataclass
class Source:
    """The run being rerun, and what the rerun will execute."""

    app_name: str
    verstr: str
    metadata: dict
    patches: dict
    log: list
    run_state: Optional[dict]
    recorded: Optional[core.Invocation]
    invocation: core.Invocation

    @property
    def code_verstr(self):
        return core.code_verstr_of(self.metadata)

    @property
    def code_key(self):
        """The code object the rerun references: the original's, or — for a
        legacy record holding its own patches — the one it gets promoted to."""
        if self.metadata.get("code"):
            return self.metadata["code"]
        diff_hash = self.metadata.get("diff_hash")
        if diff_hash and self.patches:
            return code_key(self.code_verstr, diff_hash)
        return None

    @property
    def sweep_params(self):
        """A sweep trial's params, re-exported as ``VMN_SWEEP_PARAMS``."""
        create = next((e for e in self.log if e.get("type") == "create"), {})
        return core.create_params(self.log) if (create.get("tags") or {}).get("sweep") else None


def experiment_rerun(vcs, params, storage, args, repo_lock=None):
    source, err = load_source(storage, vcs.name, args)
    if err:
        VMN_LOGGER.error(err)
        return 1
    if getattr(args, "print_only", False):
        return report.print_recipe(source, getattr(args, "json", False))
    env = _capture_env(vcs, args, source.invocation.command)
    report.warn(storage, source, env)
    if getattr(args, "dry_run", False):
        return _dry_run(vcs, source, args)
    return _execute(vcs, params, storage, args, source, env, repo_lock)


def load_source(storage, app_name, args):
    """``(Source, None)`` or ``(None, why it can't be rerun)``."""
    if getattr(args, "fork_from", None) or getattr(args, "fork_step", None) is not None:
        return None, "rerun does not take --fork-from/--fork-step"
    ref = _ref(args)
    if ref is None:
        return None, "vmn-exp rerun needs a run: -v <ref> or --latest"
    try:
        verstr = resolve_run(storage, app_name, ref, "rerun")
    except ValueError as exc:
        return None, str(exc)
    metadata, patches = _code_of(storage, app_name, *storage.load(app_name, verstr))
    blocker = core.rerun_blocker(metadata, metadata.get("code"))
    if blocker:
        return None, f"Cannot rerun {verstr}: {blocker}"
    log = storage.load_merged_log(app_name, verstr) or []
    run_state = load_run_state(storage, app_name, verstr)
    recorded = core.recorded_invocation(run_state, log)
    invocation, err = core.resolve_command(recorded, getattr(args, "run_cmd", None))
    if err:
        return None, f"Cannot rerun {verstr}: {err}"
    if getattr(args, "rerun_cwd", None):
        invocation = invocation._replace(cwd=args.rerun_cwd)
    return Source(app_name, verstr, metadata, patches, log, run_state, recorded,
                  invocation), None


def _code_of(storage, app_name, metadata, patches):
    """A dirty ``from_snapshot`` record names only its code verstr: adopt the
    one code object of that verstr the store holds, if any."""
    if metadata.get("code") or not metadata.get("from_snapshot"):
        return metadata, patches
    key = find_code_key(storage, app_name, core.code_verstr_of(metadata))
    if key is None:
        return metadata, patches
    summary = stored_code(storage, app_name, key) or {}
    _, code_patches = storage.load_record(code_app(app_name), key)
    return dict(metadata, **summary, code=key), code_patches or {}


def _capture_env(vcs, args, argv):
    if not should_capture(getattr(args, "capture_env", None), experiment_conf(vcs)):
        return None
    return capture_env_safe(_detect_python_exe(argv))


def _dry_run(vcs, source, args):
    checkouts, err = plan_workdir(vcs, source.metadata, source.patches,
                                  getattr(args, "worktree_dir", None))
    if err:
        VMN_LOGGER.error(f"Cannot rerun {source.verstr}: {err}")
        return 1
    report.print_plan(source, checkouts)
    return 0


def _execute(vcs, params, storage, args, source, env, repo_lock):
    with exit_on_termination():
        workdir, err = prepare_workdir(vcs, source.metadata, source.patches,
                                       getattr(args, "worktree_dir", None))
    if err:
        VMN_LOGGER.error(f"Cannot rerun {source.verstr}: {err}")
        return 1
    keep = getattr(args, "keep_worktree", False)
    try:
        with exit_on_termination():
            cwd, err = _child_dir(workdir, source.invocation.cwd)
            if err:
                VMN_LOGGER.error(f"Cannot rerun {source.verstr}: {err}")
                return 1
            verstr, err = _claim(storage, args, source, env)
            if err is not None:
                return err
        if repo_lock is not None:
            repo_lock.release()
        return _supervise(vcs, params, storage, args, source, verstr, workdir, cwd, keep)
    finally:
        _release_workdir(workdir, keep)


def _child_dir(workdir, rel_cwd):
    """The child's cwd inside the workspace: *rel_cwd* from the app root."""
    rel_cwd = rel_cwd or "."
    root = os.path.normpath(workdir.root)
    path = os.path.normpath(os.path.join(workdir.app_root, rel_cwd))
    if os.path.isabs(rel_cwd) or os.path.commonpath([root, path]) != root:
        return None, f"cwd {rel_cwd} is outside the restored workspace"
    if not os.path.isdir(path):
        return None, f"cwd {rel_cwd} does not exist in the run's code"
    return path, None


def _claim(storage, args, source, env):
    """``(new verstr, None)`` or ``(None, exit code)``."""
    import vmn_exp.cli.experiment as cli

    parent, err = cli._resolve_parent(storage, source.app_name, args)
    if err is not None:
        return None, err
    note = getattr(args, "note", None) or f"rerun of {source.verstr}"
    template = core.rerun_template(source.metadata, source.verstr, note, now_iso())
    key = _ensure_code(storage, source)
    if key:
        template["code"] = key
    verstr = create_run(
        storage, source.app_name, source.code_verstr, template, {}, note=note,
        create_data=_create_data(source, args), parent=parent,
        name=getattr(args, "run_name", None), env=env,
    )
    cli._append_inputs(storage, source.app_name, verstr, getattr(args, "inputs", None))
    return verstr, None


def _ensure_code(storage, source):
    """The code key the rerun references, promoting a legacy record's
    in-record patches into a code object once."""
    key = source.code_key
    if key and not source.metadata.get("code") and stored_code(
        storage, source.app_name, key
    ) is None:
        store_code(storage, source.app_name, key, source.patches,
                   _patch_summary(source.patches))
    return key


def _create_data(source, args):
    """The original create entry's params, ``-f``'s on top."""
    import vmn_exp.cli.experiment as cli

    data = {"params": core.create_params(source.log)}
    if getattr(args, "file", None):
        notes = cli._parse_notes_file(args.file)
        data["params"].update(notes.get("params") or {})
        data.update({k: notes[k] for k in ("hypothesis", "tags") if k in notes})
    return {k: v for k, v in data.items() if v}


def _supervise(vcs, params, storage, args, source, verstr, workdir, cwd, keep):
    argv = core.remap_live_paths(source.invocation.command, vcs.vmn_root_path,
                                 workdir.app_root)
    if argv != source.invocation.command:
        VMN_LOGGER.warning("Paths into the live repo in the command now point "
                           "into the restored workspace")
    experiment_dir = (params.get("experiment_dir") or os.environ.get("VMN_EXPERIMENT_DIR")
                      or vcs.vmn_root_path)
    return _Supervision(
        storage, source.app_name, verstr, args, experiment_conf(vcs),
        extra_env=core.child_env(cwd, experiment_dir, source.sweep_params),
        cwd=cwd, root=workdir.app_root,
        state_extra={"workdir": workdir.root} if keep else None,
    ).run(argv)


def _release_workdir(workdir, keep):
    if keep:
        VMN_LOGGER.info(f"Workspace kept at {workdir.root}")
    elif not workdir.cleanup():
        VMN_LOGGER.warning(f"Could not fully remove the workspace {workdir.root}")
