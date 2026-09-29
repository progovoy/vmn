"""The ``sweep`` command's argparse subparser."""

SWEEP_ACTIONS = ("create", "agent", "status")


def add_sweep_parser(subparsers):
    p = subparsers.add_parser(
        "sweep", help="Server-less hyperparameter sweeps (W&B Sweeps style)"
    )
    p.set_defaults(strict_version=False)
    p.add_argument("action", choices=SWEEP_ACTIONS,
                   help="create a sweep, run an agent on it, or show its status")
    p.add_argument("name", help="The application's name")
    p.add_argument("ref", nargs="?", default=None,
                   help="agent/status: the sweep (verstr, unique prefix, @N)")
    p.add_argument("-f", "--file", default=None, help="create: the sweep spec (YAML)")
    p.add_argument("--name", dest="run_name", default=None,
                   help="create: a human-readable name for the sweep")
    p.add_argument("--note", default=None, help="create: a note for the sweep run")
    p.add_argument("--count", type=int, default=None,
                   help="agent: run at most N trials, then exit")
    p.add_argument("--retry-failed", action="store_true", default=False,
                   help="agent: re-run trials whose latest attempt failed or got "
                        "stuck before claiming new ones")
    p.add_argument("--json", action="store_true", default=False,
                   help="status: print machine-readable JSON")
    _add_storage_flags(p)
    _add_supervision_flags(p)


def _add_storage_flags(p):
    p.add_argument("--store", default=None,
                   help="Storage URI: s3://bucket/prefix, gs://..., az://..., "
                        "file:///dir (or VMN_EXPERIMENT_STORE)")
    p.add_argument("--bucket", default=None,
                   help="S3 bucket name (shorthand for --store s3://BUCKET/PREFIX)")
    p.add_argument("--endpoint-url", default=None, help="Custom S3 endpoint URL")
    p.add_argument("--prefix", default="vmn-experiments", help="S3 key prefix")
    p.add_argument("--experiment-dir", default=None,
                   help="Write experiments to this directory instead of local .vmn/")
    p.add_argument("--writer-id", default=None,
                   help="Unique writer ID for this process (default: VMN_WRITER_ID "
                        "or hostname)")


def _add_supervision_flags(p):
    """The ``vmn-exp run`` flags that shape how an agent supervises a trial."""
    p.add_argument("--no-env", dest="capture_env", action="store_false", default=None,
                   help="skip environment capture on trial runs")
    p.add_argument("--sync-interval", type=int, default=30,
                   help="agent: seconds between remote metric syncs (default: 30)")
    p.add_argument("--heartbeat-interval", type=int, default=30,
                   help="agent: seconds between run-state heartbeats (default: 30)")
    p.add_argument("--kill-grace-sec", type=float, default=None,
                   help="agent: seconds a stopped trial gets before SIGKILL")
    p.add_argument("--no-capture-output", dest="capture_output", action="store_false",
                   default=True, help="agent: don't keep trial output as output.log")
    p.add_argument("--output-cap-mb", type=float, default=None,
                   help="agent: size cap of each trial's output.log")
    p.add_argument("--no-system-metrics", dest="system_metrics", action="store_false",
                   default=None, help="agent: don't record sys_* metrics of trials")
