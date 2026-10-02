"""vmn core's code-store helpers reach a vmn-exp storage's ``code`` area."""
import os

from vmn_exp.core.code_store import stored_code
from vmn_exp.snapshot.core_code import CoreCodeStore
from vmn_exp.storage.open import open_storage


def _runs(tmp_path):
    return open_storage(None, str(tmp_path), area="runs")


def test_the_core_pseudo_app_lands_in_the_code_area_under_the_app_key(tmp_path):
    runs = _runs(tmp_path)
    CoreCodeStore(runs).save("vmn-code/root~svc", "k", {"verstr": "k", "has_x": True}, {})
    assert os.path.isfile(tmp_path / "code" / "root-svc" / "k" / "metadata.yml")
    assert stored_code(runs, "root/svc", "k") == {"has_x": True}
    assert CoreCodeStore(runs).load_metadata("vmn-code/root~svc", "k")["verstr"] == "k"


def test_an_app_scope_reaches_the_runs_themselves(tmp_path):
    runs = _runs(tmp_path)
    runs.save("root/svc", "r1", {"verstr": "r1", "code": "k"}, {})
    listed = CoreCodeStore(runs).list_snapshots("root/svc")
    assert [m["verstr"] for m in listed] == ["r1"]


def test_capture_ensure_code_stores_through_the_code_area(tmp_path, monkeypatch):
    from vmn_exp.gitmode import capture

    seen = []
    monkeypatch.setattr(capture, "_core_ensure_code",
                        lambda store, vcs, captured: seen.append(store) or ("k", {}))
    assert capture.ensure_code(_runs(tmp_path), None, None) == ("k", {})
    seen[0].save("vmn-code/app", "k", {"verstr": "k"}, {})
    assert os.path.isfile(tmp_path / "code" / "app" / "k" / "metadata.yml")
