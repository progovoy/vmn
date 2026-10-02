"""vmn core's code-store helpers reach a vmn-exp storage's ``code`` area."""
import os

from vmn_exp.storage.open import open_storage


def _runs(tmp_path):
    return open_storage(None, str(tmp_path), area="runs")


def test_capture_ensure_code_stores_through_the_code_area(tmp_path, monkeypatch):
    from vmn_exp.gitmode import capture

    seen = []
    monkeypatch.setattr(capture, "_core_ensure_code",
                        lambda store, vcs, captured: seen.append(store) or ("k", {}))
    assert capture.ensure_code(_runs(tmp_path), None, None) == ("k", {})
    seen[0].save("root/svc", "k", {"verstr": "k"}, {})
    assert os.path.isfile(tmp_path / "code" / "root-svc" / "k" / "metadata.yml")
