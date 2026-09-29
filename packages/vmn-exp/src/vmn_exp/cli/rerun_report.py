"""What ``vmn-exp rerun`` tells the user: warnings about how faithful the
rerun will be, the ``--dry-run`` plan and the ``--print`` recipe.

``--print`` is for cluster schedulers: vmn does not schedule, it prints what a
job would run (command, repo-relative cwd, code identity) and the lines that
reproduce it on a node — ``vmn-exp rerun`` where the node has the repo, an
exported tree plus ``VMN_SNAPSHOT_METADATA`` where it has no git.
"""
import json
import shlex

from vmn_exp.cli.provenance import _load_full_env
from vmn_exp.core import rerun as core
from vmn_exp.core.provenance import env_diff
from vmn_exp.core.status import RUNNING, derive_status, run_state_observed_at
from vmn_exp.storage.files import safe_verstr
from version_stamp.api import VMN_LOGGER, _predates_untracked_capture


def recipe(source):
    """What to run, where, on which code — a JSON-ready dict."""
    inv = source.invocation
    return {
        "rerun_of": source.verstr,
        "app": source.app_name,
        "command": list(inv.command),
        "cwd": inv.cwd or ".",
        "code_verstr": source.code_verstr,
        "code": source.code_key,
        "base_commit": source.metadata.get("base_commit"),
        "recipe": f"vmn-exp rerun {source.app_name} -v {source.verstr}",
        "export_recipe": _export_recipe(source),
    }


def _export_recipe(source):
    """The git-free way: export the run's tree, run the command inside it."""
    out = safe_verstr(source.verstr)
    app = shlex.quote(source.app_name)
    cwd = source.invocation.cwd or "."
    return (
        f"vmn-exp export {app} -v {source.verstr} -o {out} && "
        f"cd {shlex.quote(f'{out}/{cwd}')} && "
        f"VMN_SNAPSHOT_METADATA=\"$OLDPWD/{out}/vmn_metadata.yml\" "
        f"vmn-exp run {app} -- {shlex.join(source.invocation.command)}"
    )


def print_recipe(source, as_json=False):
    data = recipe(source)
    if as_json:
        print(json.dumps(data))
        return
    print(f"command:       {shlex.join(data['command'])}")
    print(f"cwd:           {data['cwd']}")
    print(f"code_verstr:   {data['code_verstr']}")
    print(f"code:          {data['code'] or '(clean tree)'}")
    print(f"recipe:        {data['recipe']}")
    print(f"export_recipe: {data['export_recipe']}")


def print_plan(source, checkouts):
    """``--dry-run``: the source, the command and every checkout to restore."""
    data = recipe(source)
    print(f"Rerun of:  {source.verstr}")
    print(f"Command:   {shlex.join(data['command'])}")
    print(f"Cwd:       {data['cwd']}")
    print(f"Code:      {data['code'] or data['code_verstr'] + ' (clean tree)'}")
    print("Workspace:")
    for checkout in checkouts:
        origin = (f"worktree of {checkout.local_repo}" if checkout.local_repo
                  else f"clone of {checkout.remote}")
        steps = f" + {', '.join(checkout.steps)}" if checkout.steps else ""
        print(f"  {checkout.name}: {checkout.dest} @ {checkout.commit[:7]} "
              f"({origin}){steps}")


def warn(storage, source, env):
    """Everything that makes the rerun differ from the original run."""
    for line in _warnings(storage, source, env):
        VMN_LOGGER.warning(line)


def _warnings(storage, source, env):
    meta = source.metadata
    if _still_running(storage, source):
        yield f"{source.verstr} is still running"
    if source.recorded and source.recorded.runner == core.RUNNER_SDK:
        yield ("The source is an SDK run: the metrics its script logs land on the "
               "inner run it opens")
    if not source.invocation.cwd:
        yield "The run recorded no cwd: running from the app root"
    if meta.get("untracked_skipped"):
        yield ("Untracked files too large to capture are missing: "
               + ", ".join(meta["untracked_skipped"]))
    if _predates_untracked_capture(meta):
        yield "The run predates untracked-file capture: its untracked files are missing"
    if source.sweep_params is not None:
        yield "A sweep trial: its params are re-exported as VMN_SWEEP_PARAMS"
    yield from _env_warnings(storage, source, env)


def _still_running(storage, source):
    state = source.run_state
    # Only a run claiming to run needs the store's write time to tell running from stuck.
    if not state or state.get("state") != "running" or state.get("exit_code") is not None:
        return False
    observed = run_state_observed_at(storage, source.app_name, source.verstr)
    return derive_status(state, observed_at=observed) == RUNNING


def _env_warnings(storage, source, env):
    if env is None:
        return
    original = _load_full_env(storage, source.app_name, source.verstr)
    lines = env_diff(original, env) if original else []
    if lines:
        yield "The environment differs from the original run's:\n  " + "\n  ".join(lines)
