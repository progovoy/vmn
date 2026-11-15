"""``rerun``'s own flags: print the recipe, and where the run's code is restored."""


def add_rerun(parser):
    parser.add_argument("--print", dest="print_only", action="store_true", default=False,
                        help="rerun: print the resolved command, cwd, code identity and a "
                             "recipe (with --json as JSON); runs and creates nothing")
    parser.add_argument("--keep-worktree", action="store_true", default=False,
                        help="rerun: keep the workspace the run's code was restored into")
    parser.add_argument("--worktree-dir", default=None, metavar="DIR",
                        help="rerun: restore the run's code here (missing or empty, "
                             "outside the repo; default: a fresh dir in $TMPDIR)")
    parser.add_argument("--cwd", dest="rerun_cwd", default=None, metavar="PATH",
                        help="rerun: run the command here, relative to the restored app "
                             "root (default: the recorded cwd)")
