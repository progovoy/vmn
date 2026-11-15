"""The UI's ids and tokens come from the Random its builder hands it, never
from ``secrets``/``uuid`` directly (plan 44 G13). Formats and lengths stay
as they were, so stored tokens and sessions stay valid."""
import inspect
from urllib.parse import parse_qs, urlsplit

import pytest

from fakes.random import FakeRandom
from vmn_exp.core.real_io import RealRandom
from vmn_exp.ui import onboarding_probe, storage_access, tenancy
from vmn_exp.ui.app_deps import real_deps
from vmn_exp.ui.audit import AuditLog, audit_key
from vmn_exp.ui.auth.oidc import OIDCAuthenticator, OIDCConfig
from vmn_exp.ui.auth.principal import Principal
from vmn_exp.ui.auth.sessions import SessionService
from vmn_exp.ui.auth.tokens import PREFIX, TokenService, parse_token
from vmn_exp.ui.control_plane import SQLiteControlPlane

ISSUER = "https://idp.example"


def _cp(tmp_path):
    return SQLiteControlPlane(str(tmp_path / "cp.db"))


def _clock():
    return 100.0


@pytest.mark.parametrize("taker", [AuditLog, TokenService, SessionService, OIDCAuthenticator])
def test_ui_random_takers_have_no_real_default(taker):
    assert inspect.signature(taker).parameters["random"].default is inspect.Parameter.empty


def test_api_token_id_and_secret_come_from_random_and_keep_their_lengths(tmp_path):
    expected = FakeRandom()
    plaintext, record = TokenService(_cp(tmp_path), clock=_clock, random=FakeRandom()).create("ci", {})

    assert parse_token(plaintext) == (expected.token_hex(8), expected.token_urlsafe(32))
    assert record.id == parse_token(plaintext)[0]

    real, _ = TokenService(_cp(tmp_path), clock=_clock, random=RealRandom()).create("ci", {})
    token_id, secret = parse_token(real)
    assert real.startswith(PREFIX + "_") and len(token_id) == 16 and len(secret) == 43


def test_session_id_comes_from_random(tmp_path):
    sessions = SessionService(_cp(tmp_path), clock=_clock, random=FakeRandom())

    session_id = sessions.open(Principal("oidc:a", "a", {}))

    assert session_id == FakeRandom().token_urlsafe(32)
    assert sessions.principal(session_id).id == "oidc:a"


class RecordingStore:
    def __init__(self):
        self.put_calls = []

    def put(self, kind, key, doc):
        self.put_calls.append((kind, key, doc))


def test_audit_entry_id_is_time_key_plus_random_suffix():
    audit = AuditLog(RecordingStore(), clock=lambda: 1.5, random=FakeRandom())

    entry = audit.record("u1", "login")

    assert entry["id"] == f"{audit_key(1.5)}-{FakeRandom().token_hex(4)}"


class DiscoveryHttp:
    def get_json(self, url):
        return {"issuer": ISSUER, "authorization_endpoint": ISSUER + "/authorize",
                "token_endpoint": ISSUER + "/token"}


def test_oidc_state_nonce_and_verifier_come_from_random(tmp_path):
    cp = _cp(tmp_path)
    config = OIDCConfig(issuer=ISSUER, client_id="vmn", redirect_uri="https://vmn/cb")
    oidc = OIDCAuthenticator(config, cp, verifier=None, http=DiscoveryHttp(),
                             clock=_clock, random=FakeRandom())

    query = parse_qs(urlsplit(oidc.login_url()).query)

    expected = FakeRandom()
    state, nonce, verifier = (expected.token_urlsafe(24), expected.token_urlsafe(24),
                              expected.token_urlsafe(48))
    assert query["state"] == [state] and query["nonce"] == [nonce]
    assert cp.pop("login", state, now=_clock()) == {"nonce": nonce, "verifier": verifier}


def test_real_deps_hand_the_audit_log_and_tokens_the_io_random(tmp_path):
    from fakes.clock import FakeClock
    from fakes.console import FakeConsole
    from fakes.env import FakeEnv
    from fakes.host import FakeHost
    from fakes.processes import FakeProcesses
    from vmn_exp.core.ports import IO

    rnd = FakeRandom()
    io = IO(clock=FakeClock(), env=FakeEnv(), processes=FakeProcesses(), random=rnd,
            host=FakeHost(), console=FakeConsole())
    deps = real_deps(io, _cp(tmp_path), background_refresh=False, read_only=False,
                     keep_warm=None)

    assert deps.audit.random is rnd and deps.token_service.random is rnd


class ClaimingStore:
    def __init__(self):
        self.claimed = []

    def create_exclusive(self, scope, key, metadata, data):
        self.claimed.append(key)
        return True


def test_store_probe_key_comes_from_random():
    store = ClaimingStore()

    key = storage_access._claim_probe_key(store, FakeRandom())

    assert key == store.claimed[0] == f"probe-{FakeRandom().hex_id()}"


def test_role_probe_key_comes_from_random():
    assert onboarding_probe._probe_key("team", FakeRandom()) == (
        f"team/{onboarding_probe.SERVER_AREA}/probe-{FakeRandom().hex_id()}")


class InsertingConn:
    def __init__(self):
        self.params = None

    def execute(self, sql, params):
        self.params = params
        return self

    def fetchone(self):
        return (7,)


def test_org_external_id_comes_from_random():
    conn = InsertingConn()

    org = tenancy.create_org(conn, "acme", FakeRandom())

    assert org.external_id == f"vmn-{FakeRandom().token_hex(16)}"
    assert conn.params == ("acme", org.external_id)
