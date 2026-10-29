"""``vmn-exp run`` records its attempt id in ``run_state.yml``, like an SDK run."""
from exp_helpers import _PY, _bootstrap, _experiment, _storage, extract_dev_verstr

from vmn_exp.core.status import load_run_state


def _cli_run_state(app_layout, capfd):
    capfd.readouterr()
    code = _experiment(
        app_layout.app_name, action="run", run_cmd=[_PY, "-c", "print('ok')"]
    )
    assert code == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    return load_run_state(_storage(app_layout), app_layout.app_name, verstr)


def test_cli_run_state_carries_an_attempt_id(app_layout, capfd):
    _bootstrap(app_layout)

    first = _cli_run_state(app_layout, capfd)
    second = _cli_run_state(app_layout, capfd)

    assert isinstance(first.get("attempt"), str) and first["attempt"]
    assert first["attempt"] != second["attempt"]
