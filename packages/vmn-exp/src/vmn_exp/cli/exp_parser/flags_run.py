"""How ``run`` (and ``rerun``) supervise the command they launch."""


def add_supervision(parser):
    parser.add_argument("--sync-interval", type=int, default=None,
                        help="Seconds between remote syncs during 'run' (default: "
                             "VMN_EXP_SYNC_SEC, else conf sync_interval_sec, else 30).")
    parser.add_argument("--heartbeat-interval", type=int, default=None,
                        help="Seconds between run-state heartbeats during 'run' (default: "
                             "VMN_EXP_HEARTBEAT_SEC, else conf heartbeat_interval_sec, "
                             "else 30).")
    parser.add_argument("--kill-grace-sec", type=float, default=None,
                        help="Seconds a child gets to exit after a forwarded signal "
                             "before it is killed during 'run' (default: "
                             "VMN_EXP_KILL_GRACE_SEC, else 15).")
    parser.add_argument("--no-capture-output", dest="capture_output", action="store_false",
                        default=True,
                        help="run: don't keep the command's stdout/stderr as the output.log "
                             "artifact (it still streams to the terminal).")
    parser.add_argument("--output-cap-mb", type=float, default=None,
                        help="run: size cap of output.log; past it the first and last "
                             "halves are kept (default: VMN_EXP_OUTPUT_CAP_MB or 10).")
    parser.add_argument("--no-system-metrics", dest="system_metrics", action="store_false",
                        default=None,
                        help="run: don't record the child process tree's CPU/memory/GPU "
                             "as sys_* metrics. Overrides VMN_SYSTEM_METRICS and conf "
                             "system_metrics settings.")
    parser.add_argument("--no-adopt", dest="adopt_run", action="store_false", default=True,
                        help="run: don't offer this run to the command; a start_run() "
                             "in it opens a run nested under this one. Same as "
                             "VMN_EXP_ADOPT=0.")
