"""Flags that describe a new run (create, run, rerun) or what add writes onto one."""


def add_name(parser):
    parser.add_argument("--name", dest="run_name", default=None,
                        help="create/run: a human-readable name for the run")


def add_new_app(parser):
    parser.add_argument("--new-app", action="store_true", default=False,
                        help="create/run: confirm that this app name is genuinely new when "
                             "other vmn apps already exist in this repo")


def add_note(parser):
    parser.add_argument("--note", default=None, help="Note or description")


def add_file(parser):
    parser.add_argument("-f", "--file", default=None,
                        help="YAML file with structured notes/params")


def add_metrics(parser):
    parser.add_argument("--metrics", nargs="*", action="extend", default=None,
                        help="Metrics as key=value pairs (e.g., loss=0.34 acc=0.91); "
                             "repeatable, each --metrics adds to the earlier ones")


def add_attach(parser):
    parser.add_argument("--attach", default=None, help="File to attach as artifact")


def add_capture_env(parser):
    parser.add_argument("--no-env", dest="capture_env", action="store_false", default=None,
                        help="create/run: skip environment capture (packages, python, "
                             "platform). Overrides VMN_CAPTURE_ENV and conf capture_env "
                             "settings.")


def add_inputs(parser):
    parser.add_argument("--input", action="append", dest="inputs", default=None,
                        metavar="[NAME=]URI[#DIGEST]",
                        help="create/run/add: record a dataset or artifact input. "
                             "Optional name= prefix and #digest suffix. Repeatable.")


def add_parent(parser):
    parser.add_argument("--parent", default=None,
                        help="Parent experiment for a nested run.")


def add_fork(parser):
    parser.add_argument("--fork-from", default=None, metavar="REF",
                        help="create/run: start a new run with REF's metrics and params "
                             "(up to --fork-step; 'REF?_step=N' also works)")
    parser.add_argument("--fork-step", type=int, default=None, metavar="N",
                        help="create/run: with --fork-from, copy history up to step N "
                             "(default: all of it)")
