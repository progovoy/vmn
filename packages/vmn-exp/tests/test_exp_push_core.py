"""``push_run``: a local run uploaded to a remote store, resumably, with its
code object; the per-run ledger makes an unchanged run cost no remote call."""
import pytest
from push_helpers import (
    APP, KEY, PAYLOAD, WRITER, X, add_lines, line, local_log, local_root, make_run,
    remote_log, run_meta, set_state,
)
from s3_helpers import mocked_bucket, put_raw, record_calls, s3_storage

from vmn_exp.core.code_store import code_storage, stored_code
from vmn_exp.core.push_code import CodePusher
from vmn_exp.core.push_identity import run_identity
from vmn_exp.core.push_ledger import PushLedger, remote_id
from vmn_exp.core.push_run import (
    COLLISION, FAILED, NEW, UP_TO_DATE, UPDATE, push_run, require_push_target,
)
from vmn_exp.core.status import RUN_STATE_FILE
from vmn_exp.storage.files import log_object_name
from vmn_exp.storage.s3_records import CLAIM_FILE


@pytest.fixture
def target(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield s3_storage()


@pytest.fixture
def local(tmp_path):
    return local_root(tmp_path)


def _puts(calls, part=""):
    return [p["Key"] for op, p in calls if op == "PutObject" and part in p["Key"]]


# -- identity ----------------------------------------------------------------


def test_identity_ignores_verstr_and_archived():
    renamed = run_meta("other", archived=True, note="n", code="elsewhere")
    assert run_identity(APP, run_meta()) == run_identity(APP, renamed)
    assert run_identity(APP, run_meta()) != run_identity("app2", run_meta())
    assert run_identity(APP, run_meta()) != run_identity(
        APP, run_meta(timestamp="2026-02-02T00:00:00Z")
    )


def test_identity_uses_imported_run_id():
    first = run_meta(imported_from={"run_id": "a"})
    second = run_meta(imported_from={"run_id": "b"})
    assert run_identity(APP, first) != run_identity(APP, second)


# -- target and ledger ---------------------------------------------------------


def test_push_requires_capable_remote_target(local, target):
    require_push_target(target)
    with pytest.raises(ValueError, match="rsync"):
        require_push_target(local)


def test_ledger_lives_under_push_dir_and_is_not_listed(local, target, tmp_path):
    make_run(local, tmp_path)
    assert push_run(local, target, APP, X).status == NEW
    ledger = PushLedger(local, APP, remote_id(target))
    assert f"/.push/{remote_id(target)}" in ledger.dir.replace("\\", "/")
    assert ledger.get(X)["complete"] is True
    assert local.list_verstrs(APP) == [X]


# -- round trip and resume ---------------------------------------------------


def test_push_new_run_roundtrips_everything(local, target, tmp_path):
    make_run(local, tmp_path)
    outcome = push_run(local, target, APP, X)
    assert (outcome.verstr, outcome.status) == (X, NEW)
    assert target.load_metadata(APP, X) == local.load_metadata(APP, X)
    assert remote_log(target) == local_log(local)
    for name in ("env.yml", RUN_STATE_FILE):
        assert target.load_file(APP, X, name) == local.load_file(APP, X, name)
    assert target.list_artifacts(APP, X) == local.list_artifacts(APP, X)
    _, patches = target.load(APP, X)
    assert patches == PAYLOAD


def test_second_push_makes_no_remote_calls(local, target, tmp_path):
    make_run(local, tmp_path)
    push_run(local, target, APP, X)
    calls = record_calls(target._s3)
    assert push_run(local, target, APP, X).status == UP_TO_DATE
    assert calls == []


def test_repush_ships_only_new_lines(local, target, tmp_path):
    make_run(local, tmp_path)
    set_state(local, X, "running")  # no compaction: the segments stay apart
    push_run(local, target, APP, X)
    add_lines(local, X, [line(3)])
    calls = record_calls(target._s3)
    assert push_run(local, target, APP, X).status == UPDATE
    shipped = [p["Key"].rsplit("/", 1)[1] for op, p in calls
               if op == "PutObject" and "/log." in p["Key"]]
    assert shipped == [log_object_name(WRITER, 1)]
    assert target.load_file(APP, X, shipped[0]) == line(3).encode()
    assert remote_log(target) == local_log(local)


def test_partial_line_is_not_shipped(local, target, tmp_path):
    make_run(local, tmp_path)
    add_lines(local, X, ['{"half": '])
    push_run(local, target, APP, X)
    assert remote_log(target) == (line(1) + line(2)).encode()
    add_lines(local, X, ['1}\n'])
    push_run(local, target, APP, X)
    assert remote_log(target) == local_log(local)


def test_repush_uploads_only_new_artifact(local, target, tmp_path):
    make_run(local, tmp_path)
    push_run(local, target, APP, X)
    extra = tmp_path / "extra.bin"
    extra.write_bytes(b"more")
    local.save_artifact_file(APP, X, str(extra))
    calls = record_calls(target._s3)
    push_run(local, target, APP, X)
    assert [k.rsplit("/", 1)[1] for k in _puts(calls, "/artifacts/")] == ["extra.bin"]


def test_output_log_and_media_are_pushed(local, target, tmp_path):
    make_run(local, tmp_path)
    src = tmp_path / "out"
    src.write_bytes(b"stdout")
    local.save_artifact_file(APP, X, str(src), name="output.log")
    local.save_artifact_file(APP, X, str(src), name="media/img/0.png")
    push_run(local, target, APP, X)
    names = {a["name"] for a in target.list_artifacts(APP, X)}
    assert {"output.log", "media/img/0.png"} <= names


def test_push_resumes_after_artifact_upload_failure(local, target, tmp_path, monkeypatch):
    make_run(local, tmp_path)
    upload = target.save_artifact_file

    def broken(*args, **kwargs):
        raise OSError("network down")

    monkeypatch.setattr(target, "save_artifact_file", broken)
    assert push_run(local, target, APP, X).status == FAILED
    monkeypatch.setattr(target, "save_artifact_file", upload)
    assert push_run(local, target, APP, X).status == UPDATE
    assert target.list_artifacts(APP, X) == local.list_artifacts(APP, X)
    assert remote_log(target) == local_log(local)


def test_push_resumes_own_crashed_claim(local, target, tmp_path):
    make_run(local, tmp_path)
    identity = run_identity(APP, local.load_metadata(APP, X))
    put_raw(f"{target._key_prefix(APP, X)}/{CLAIM_FILE}", identity.encode())
    assert push_run(local, target, APP, X).status == NEW
    assert target.load_metadata(APP, X) is not None


def test_foreign_claim_without_metadata_is_a_collision(local, target, tmp_path):
    make_run(local, tmp_path)
    put_raw(f"{target._key_prefix(APP, X)}/{CLAIM_FILE}", b"")
    assert push_run(local, target, APP, X).status == COLLISION


# -- code objects ---------------------------------------------------------------


def test_code_object_pushed_before_claim(local, target, tmp_path):
    make_run(local, tmp_path)
    calls = record_calls(target._s3)
    push_run(local, target, APP, X)
    keys = _puts(calls)
    marker = next(i for i, k in enumerate(keys) if "/code/" in k and "metadata" in k)
    payload = next(i for i, k in enumerate(keys) if "/code/" in k and "untracked" in k)
    claim = next(i for i, k in enumerate(keys) if k.endswith(CLAIM_FILE) and "/code/" not in k)
    assert payload < marker < claim


def test_code_object_already_on_remote_not_reuploaded(local, target, tmp_path):
    make_run(local, tmp_path)
    code_storage(target).save(APP, KEY, {"verstr": KEY}, PAYLOAD)
    calls = record_calls(target._s3)
    code = CodePusher(local, target, APP)
    push_run(local, target, APP, X, code=code)
    assert _puts(calls, "/code/") == []
    assert (code.uploaded, code.present) == (0, 1)


def test_code_object_recreated_if_pruned_between_upload_and_claim(
    local, target, tmp_path, monkeypatch
):
    make_run(local, tmp_path)
    claim = target.create_exclusive

    def pruned_first(*args, **kwargs):
        code_storage(target).delete(APP, KEY)
        return claim(*args, **kwargs)

    monkeypatch.setattr(target, "create_exclusive", pruned_first)
    assert push_run(local, target, APP, X).status == NEW
    assert stored_code(target, APP, KEY) is not None


def test_runs_sharing_code_upload_it_once(local, target, tmp_path):
    make_run(local, tmp_path)
    make_run(local, tmp_path, verstr=X + ".2", timestamp="2026-01-02T00:00:00Z")
    code = CodePusher(local, target, APP)
    calls = record_calls(target._s3)
    for verstr in (X, X + ".2"):
        assert push_run(local, target, APP, verstr, code=code).status == NEW
    assert len(_puts(calls, "/code/app/" + KEY + "/metadata")) == 1
    assert code.uploaded == 1


def test_missing_local_code_object_reported_not_fatal(local, target, tmp_path):
    make_run(local, tmp_path, code=False)
    outcome = push_run(local, target, APP, X)
    assert outcome.status == NEW
    assert any("code missing locally" in w for w in outcome.warnings)
