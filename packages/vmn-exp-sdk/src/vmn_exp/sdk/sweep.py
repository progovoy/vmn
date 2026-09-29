"""The params of the sweep trial this process runs (``vmn-exp sweep agent``)."""
import json
import os

SWEEP_PARAMS_ENV = "VMN_SWEEP_PARAMS"


def sweep_params():
    """The trial's params as a dict — ``{}`` outside a sweep.

    ``vmn-exp sweep agent`` exports them to the trial's command as JSON in
    ``$VMN_SWEEP_PARAMS`` (next to the ``--name=value`` arguments the command
    template adds). Each call returns a fresh dict.
    """
    raw = os.environ.get(SWEEP_PARAMS_ENV)
    if not raw:
        return {}
    params = json.loads(raw)
    if not isinstance(params, dict):
        raise ValueError(f"{SWEEP_PARAMS_ENV} must hold a JSON object, got {raw[:80]!r}")
    return params
