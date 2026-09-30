"""The vmn-exp suite's helpers: vmn's (tests/helpers.py, re-exported with its
private names) plus the vmn-exp command/storage helpers."""
import os

import helpers
from version_stamp.core.logging import reset_logger
from vmn_exp.cli.main import vmn_exp_run

# Every helpers name, private ones too (``import *`` would skip those).
globals().update({k: v for k, v in vars(helpers).items() if not k.startswith("__")})

# The three distributions' source roots (see docs/packaging.md), as a PYTHONPATH.
SRC_DIRS = [
    os.path.join(helpers._PROJECT_ROOT, "packages", dist, "src")
    for dist in ("vmn", "vmn-exp-sdk", "vmn-exp")
]
_SRC_PATH = os.pathsep.join(SRC_DIRS)


def _storage(app_layout, subdir="experiments"):
    from vmn_exp.snapshot import open_storage

    return open_storage(vmn_root_path=app_layout.repo_path, subdir=subdir)


def _experiment(
    app_name,
    action="create",
    version=None,
    note=None,
    metrics=None,
    file=None,
    attach=None,
    sort=None,
    top=None,
    latest=None,
    tool=None,
    output=None,
    keep=None,
    older_than=None,
    last=None,
    run_cmd=None,
    command="experiment",
    extra_args=None,
):
    args_list = [command]
    if action != "create":
        args_list.append(action)
    args_list.append(app_name)
    if version is not None:
        if isinstance(version, list):
            for v in version:
                args_list.extend(["-v", v])
        else:
            args_list.extend(["-v", version])
    if last is not None:
        args_list.extend(["--last", str(last)])
    if note is not None:
        args_list.extend(["--note", note])
    if metrics is not None:
        args_list.append("--metrics")
        args_list.extend(metrics)
    if file is not None:
        args_list.extend(["-f", file])
    if attach is not None:
        args_list.extend(["--attach", attach])
    if sort is not None:
        args_list.extend(["--sort", sort])
    if top is not None:
        args_list.extend(["--top", str(top)])
    if latest:
        args_list.append("--latest")
    if tool is not None:
        args_list.extend(["--tool", tool])
    if output is not None:
        args_list.extend(["-o", output])
    if keep is not None:
        args_list.extend(["--keep", str(keep)])
    if older_than is not None:
        args_list.extend(["--older-than", older_than])
    if extra_args:
        args_list.extend(extra_args)
    if run_cmd is not None:
        args_list.append("--")
        args_list.extend(run_cmd)

    reset_logger()
    return vmn_exp_run(args_list)[0]


def _exp(app_name, **kwargs):
    return _experiment(app_name, command="exp", **kwargs)


def cli_module(argv):
    """The ``-m`` module that runs *argv*: vmn-exp's commands, or vmn's."""
    if argv and argv[0] in ("exp", "experiment", "model", "ui"):
        return "vmn_exp.cli"
    return "version_stamp.cli.entry"
