"""Who writes is resolved from the Env and host handed down from a root, or
from a writer id a root already resolved (plan 44 G12): journals, registry
and comment logs, sweep claims and identities never read the process
environment."""
import pytest

from fakes.env import FakeEnv
from fakes.host import FakeHost
from vmn_exp.core import identity, writer
from vmn_exp.core.sweep.claims import claim_next_trial
from vmn_exp.core.sweep.spec import parse_spec
from vmn_exp.registry.log import _build_entry
from vmn_exp.storage.journal import _JournalState
from vmn_exp.storage.local import LocalSnapshotStorage

POD = FakeEnv({"VMN_WRITER_ID": "pod-1", "USER": "alice", "VMN_EXP_AUTHOR": "a@x.io"})


@pytest.fixture(autouse=True)
def _process_env_says_otherwise(monkeypatch):
    for key, value in {"VMN_WRITER_ID": "process-writer", "HOSTNAME": "process-host",
                       "USER": "process-user", "VMN_EXP_AUTHOR": "process@x.io"}.items():
        monkeypatch.setenv(key, value)
    writer._WRITER_ID = None


class _Copy:
    def stream_owner(self, app_name, verstr, writer_id):
        return "o7"


def test_the_process_environment_lookups_are_gone():
    assert not hasattr(writer, "process_writer_id")
    assert not hasattr(writer, "process_run_suffix")


def test_own_stream_names_the_writer_it_is_given():
    assert writer.own_stream(_Copy(), "app", "v", "pod-9") == "pod-9~o7"


def test_resolved_writer_id_is_none_until_a_root_resolves_one():
    assert writer.resolved_writer_id() is None
    writer.get_writer_id(POD, FakeHost())
    assert writer.resolved_writer_id() == "pod-1"


def test_sync_to_remote_without_a_writer_ships_the_resolved_writers_stream():
    synced = []

    class Copy(_Copy):
        def sync_log_to_remote(self, app_name, verstr, stream):
            synced.append(stream)

    writer.get_writer_id(POD, FakeHost())
    writer.sync_to_remote(Copy(), "app", "v")

    assert synced == ["pod-1~o7"]


def test_a_journal_without_a_writer_id_stamps_the_resolved_writer():
    keys = []

    class Sink:
        def put(self, key):
            keys.append(key)

    writer.get_writer_id(POD, FakeHost())
    _JournalState(Sink(), None, 1, lambda attempt: None, lambda: 1.0).record(
        "runs", "app", "v")

    assert "_pod-1_" in keys[0]


def test_a_registry_entry_stamps_the_writer_of_the_given_env():
    entry = _build_entry([], "alias", {}, env=POD, host=FakeHost(), alias="prod", version=1)

    assert (entry["writer"], entry["pos"]) == ("pod-1", 0)


def test_identity_reads_the_os_user_and_author_of_the_given_env():
    assert identity._os_user(POD) == "alice"
    assert identity.env_author(POD) == ("env", "a@x.io")
    assert identity.env_author(FakeEnv()) == ("env", "")


def test_a_claim_requires_its_agent(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path), "runs")
    spec = parse_spec({"method": "grid", "metric": {"name": "loss", "goal": "min"},
                       "parameters": {"x": {"values": [1]}}})

    claim = claim_next_trial(storage, "app", "0.0.1", spec, "pod-1:42")

    assert claim["agent"] == "pod-1:42"
    with pytest.raises(TypeError):
        claim_next_trial(storage, "app", "0.0.1", spec)


def test_a_new_runs_ids_are_the_writer_and_run_suffix_of_the_given_env():
    offline = FakeEnv({"VMN_EXP_OFFLINE": "1"})

    assert writer.new_run_ids(POD, FakeHost()) == {"writer": "pod-1", "suffix": "pod-1"}
    writer._WRITER_ID = None
    assert writer.new_run_ids(offline, FakeHost(hostname="h")) == {"writer": "h", "suffix": "h"}


def test_a_sweep_agent_is_the_writer_of_the_given_env_and_the_hosts_pid():
    from vmn_exp.cli.sweep.agent import agent_id

    assert agent_id(POD, FakeHost(pid=42)) == "pod-1:42"
