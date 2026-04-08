#!/usr/bin/env python3
"""CLI entry point: main(), vmn_run(), VMNContainer."""
import copy
import os
import pathlib
import sys
from pprint import pformat

from filelock import FileLock

from version_stamp import version as version_mod
from version_stamp.backends.factory import get_client
from version_stamp.core.constants import BOLD_CHAR, END_CHAR, VMN_BE_TYPE_GIT, VMN_BE_TYPE_LOCAL_FILE
from version_stamp.core.logging import VMN_LOGGER, _runtime_ctx, init_stamp_logger, measure_runtime_decorator
from version_stamp.core.utils import resolve_root_path
from version_stamp.cli.args import parse_user_commands
from version_stamp.cli.constants import LOCK_FILE_ENV, LOCK_FILENAME, LOG_FILENAME, VMN_ARGS
from version_stamp.stamping.publisher import VersionControlStamper

# Import all command handlers so dynamic dispatch works
from version_stamp.cli.commands import (  # noqa: F401
    handle_init,
    handle_init_app,
    handle_stamp,
    handle_release,
    handle_show,
    handle_gen,
    handle_goto,
    handle_add,
    handle_snapshot,
)
from version_stamp.cli.config_tui import handle_config  # noqa: F401


class VMNContainer(object):
    @measure_runtime_decorator
    def __init__(self, args, root_path):
        self.args = args
        root = False
        if "root" in self.args:
            root = self.args.root

        initial_params = {"root": root, "name": None, "root_path": root_path}

        if "name" in self.args and self.args.name:
            validate_app_name(self.args)
            initial_params["name"] = self.args.name

            if "command" in self.args and "stamp" in self.args.command:
                initial_params["extra_commit_message"] = self.args.extra_commit_message

        self.params = initial_params
        self.vcs = None

        # Currently this is used only for show and only for cargo situation
        # TODO:: think if this feature should exist at all
        self.params["be_type"] = VMN_BE_TYPE_GIT
        if "from_file" in self.args and self.args.from_file:
            self.params["be_type"] = VMN_BE_TYPE_LOCAL_FILE

        self.vcs = VersionControlStamper(self.params)


def validate_app_name(args):
    if args.name.startswith("/"):
        VMN_LOGGER.error("App name cannot start with /")
        raise RuntimeError()
    if "-" in args.name:
        VMN_LOGGER.error("App name cannot include -")
        raise RuntimeError()

def main(command_line=None):
    # Please KEEP this function exactly like this
    # The purpose of this function is to keep the return
    # value to be an integer
    res, _ = vmn_run(command_line)

    return res


@measure_runtime_decorator
def vmn_run(command_line=None):
    try:
        init_stamp_logger()
        args = parse_user_commands(command_line)
    except Exception:
        VMN_LOGGER.error("Logged exception: ", exc_info=True)
        return 1, None

    try:
        if args.command == "show":
            init_stamp_logger(debug=args.debug, supress_stdout=True)
        else:
            init_stamp_logger(debug=args.debug)

        root_path = resolve_root_path()
        vmn_path = os.path.join(root_path, ".vmn")
        pathlib.Path(vmn_path).mkdir(parents=True, exist_ok=True)

    except Exception:
        VMN_LOGGER.error(
            "Failed to init logger. "
            "Maybe you are running from a non-managed directory?"
        )
        VMN_LOGGER.debug("Logged exception: ", exc_info=True)

        return 1, None

    err = 0
    vmnc = None
    try:
        lock_file_path = os.path.join(vmn_path, LOCK_FILENAME)
        if LOCK_FILE_ENV in os.environ:
            lock_file_path = os.environ[LOCK_FILE_ENV]

        lock = FileLock(lock_file_path)

        # start of non-parallel code section
        lock.acquire()

        if args.command == "show":
            init_stamp_logger(
                os.path.join(vmn_path, LOG_FILENAME), args.debug, supress_stdout=True
            )
        else:
            init_stamp_logger(
                os.path.join(vmn_path, LOG_FILENAME), args.debug
            )

        command_line = copy.deepcopy(command_line)

        if command_line is None or not command_line:
            command_line = sys.argv
            if command_line is None:
                command_line = ["vmn"]

        if not command_line[0].endswith("vmn"):
            command_line.insert(0, "vmn")

        VMN_LOGGER.debug(
            f"\n{BOLD_CHAR}Command line: {' '.join(command_line)}{END_CHAR}"
        )

        # Call the actual function
        err, vmnc = _vmn_run(args, root_path)
        # We only need it here. In other, Exception cases -
        # the unlock will happen naturally because the process will exit
        lock.release()

    except Exception:
        VMN_LOGGER.error(
            "vmn_run raised exception. Run vmn --debug for details"
        )
        VMN_LOGGER.debug("Exception info: ", exc_info=True)

        err = 1

    VMN_LOGGER.debug(pformat(_runtime_ctx.call_count))

    return err, vmnc


@measure_runtime_decorator
def _vmn_run(args, root_path):
    vmnc = VMNContainer(args, root_path)
    if vmnc.args.command not in VMN_ARGS:
        VMN_LOGGER.info("Run vmn -h for help")
        return 1, vmnc

    if VMN_ARGS[vmnc.args.command] == "remote" or (
        "pull" in vmnc.args and vmnc.args.pull
    ):
        err = vmnc.vcs.backend.prepare_for_remote_operation()
        if err:
            VMN_LOGGER.error(
                "Failed to run prepare for remote operation.\n"
                "Check the log. Aborting remote operation."
            )
            return err, vmnc

        if vmnc.vcs.name is not None:
            # If there is no remote branch set, it is impossible
            # to understand if there are outgoing changes. Thus this is required for
            # remote operations.
            # TODO:: verify that this assumaption is correct
            configured_repos = set(vmnc.vcs.configured_deps.keys())
            local_repos = set(vmnc.vcs.actual_deps_state.keys())
            common_deps = configured_repos & local_repos
            common_deps.remove(".")

            for repo in common_deps:
                full_path = os.path.join(vmnc.vcs.vmn_root_path, repo)

                dep_be, err = get_client(full_path, vmnc.vcs.be_type)
                if err:
                    err_str = "Failed to create backend {0}. Exiting".format(err)
                    VMN_LOGGER.error(err_str)
                    raise RuntimeError(err_str)

                dep_be.prepare_for_remote_operation()
                del dep_be

    cmd = vmnc.args.command.replace("-", "_")
    err = getattr(sys.modules[__name__], f"handle_{cmd}")(vmnc)

    return err, vmnc




if __name__ == "__main__":
    ret_err = main()
    if ret_err:
        sys.exit(1)
    sys.exit(0)
