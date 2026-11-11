"""The vmn-exp unit lane (``./tests/run_pytest.sh --suite exp-unit``): fakes
only, no Docker, no real sleep or subprocess. The parent conftest's autouse
fixtures still apply."""
import pathlib

import pytest

from unit_guard import no_real_io, refuse_docker_fixtures

HERE = pathlib.Path(__file__).resolve().parent


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "real_io: a contract test of a real IO implementation; the unit guard lets it through"
    )


def pytest_collection_modifyitems(items):
    # A fake/real contract test (test_ports_contract.py) runs its "real" side
    # against the real implementation by design.
    for item in items:
        callspec = getattr(item, "callspec", None)
        if HERE in item.path.parents and callspec is not None and callspec.params.get("side") == "real":
            item.add_marker(pytest.mark.real_io)


@pytest.fixture(autouse=True)
def _unit_guard(request):
    refuse_docker_fixtures(request.fixturenames)
    if request.node.get_closest_marker("real_io"):
        yield
        return
    with no_real_io() as violations:
        yield
    if violations:
        pytest.fail(f"a unit test reached real {', '.join(violations)}")
