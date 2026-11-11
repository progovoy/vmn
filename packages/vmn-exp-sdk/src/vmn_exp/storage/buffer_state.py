#!/usr/bin/env python3
"""The run states a direct-to-bucket log buffer holds.

A run's state is written inline to the buffer and uploaded in the background,
so until the remote holds the final state the buffer is its only copy: the
buffer may go only once the remote's state is final (plan 40 C13).
"""
from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.state_cas import publish_final_if_unfinished
from vmn_exp.core.status import load_run_state, run_finished


def unpublished_final_states(local, remote):
    """The verstrs whose final state *local* alone holds, after one attempt
    to publish each: a remote already final (this attempt's or another's)
    needs none."""
    return [
        verstr
        for app_name, verstr, state in _finished_runs(local)
        if not _published(remote, app_name, verstr, state)
    ]


def _finished_runs(local):
    for app_name in local.list_apps():
        for verstr in local.list_verstrs(app_name):
            state = load_run_state(local, app_name, verstr) or {}
            if state.get("state") == "finished":
                yield app_name, verstr, state


def _published(remote, app_name, verstr, state):
    try:
        if publish_final_if_unfinished(remote, app_name, verstr, state):
            return True
    except Exception:
        VMN_LOGGER.debug(f"Publishing the final state of {verstr} failed", exc_info=True)
        return False
    return run_finished(remote, app_name, verstr)  # this attempt's or another's
