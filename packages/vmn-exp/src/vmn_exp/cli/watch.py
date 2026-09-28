"""``vmn-exp watch <app>``: alert runs that went failed or stuck.

A dead process cannot say it died, so ``stuck`` needs an outside observer:
run this from cron (one-shot) or leave it looping with ``--interval``. Each run
alerts once per transition, so overlapping watchers and repeated ticks stay
quiet. ``failed`` alerts the supervising process already delivered are not
sent again.
"""
import time

from vmn_exp.cli.prune import _parse_duration
from vmn_exp.core.alerts import Alerter, load_alert_config, watch_app
from version_stamp.api import VMN_LOGGER

DEFAULT_WITHIN = "1d"


def experiment_watch(vcs, storage, app_name, args):
    try:
        within_sec = _parse_duration(args.within or DEFAULT_WITHIN).total_seconds()
    except ValueError as exc:
        VMN_LOGGER.error(str(exc))
        return 1
    alerter = Alerter(load_alert_config(app_name, getattr(vcs, "experiment", None)))
    if not alerter.wants("failed") and not alerter.wants("stuck"):
        VMN_LOGGER.error(
            "No alert sink is configured for 'failed' or 'stuck': set "
            "experiment.alerts in conf.yml, or VMN_EXP_ALERT_* and VMN_EXP_ALERT_ON."
        )
        return 1
    while True:
        for verstr, status in watch_app(storage, app_name, alerter, within_sec):
            print(f"{verstr} {status}")
        if not args.interval:
            return 0
        time.sleep(args.interval)
