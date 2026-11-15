"""JwksVerifier: RS256 id_token signatures against the IdP's JWKS (pure, on fakes)."""
import base64

import pytest
from oidc_test_keys import (
    JWKS_URI,
    OPENSSL_SIGNED_TOKEN,
    OTHER_N,
    SHORT_N,
    b64url,
    jwk,
    jwks,
    sign_rs256,
    signed_jwt,
)
from vmn_exp.ui.auth.jwks import JwksVerifier
from vmn_exp.ui.auth.oidc import OIDCError

CLAIMS = {"iss": "https://idp.example", "sub": "u1"}


class FakeHttp:
    def __init__(self, *docs):
        self.docs = list(docs) or [jwks()]
        self.fetches = []

    def get_json(self, url):
        self.fetches.append(url)
        return self.docs[min(len(self.fetches), len(self.docs)) - 1]


class FakeClock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def _verifier(*docs):
    http = FakeHttp(*docs)
    clock = FakeClock()
    return JwksVerifier(http, clock), http, clock


def _refused(verifier, token, match):
    with pytest.raises(OIDCError, match=match):
        verifier.verify(token, JWKS_URI)


def test_valid_rs256_token_verifies():
    verifier, http, _ = _verifier()
    verifier.verify(signed_jwt(CLAIMS), JWKS_URI)
    verifier.verify(OPENSSL_SIGNED_TOKEN, JWKS_URI)
    assert http.fetches == [JWKS_URI]


def test_tampered_payload_is_refused():
    head, _, sig = signed_jwt(CLAIMS).split(".")
    forged = b64url(b'{"iss": "https://idp.example", "sub": "admin"}')
    _refused(_verifier()[0], f"{head}.{forged}.{sig}", "signature")


def test_alg_none_is_refused():
    head = b64url(b'{"alg": "none"}')
    body = b64url(b'{"sub": "u1"}')
    _refused(_verifier()[0], f"{head}.{body}.", "'none'")


def test_es256_fails_closed_naming_alg():
    token = sign_rs256({"alg": "ES256", "kid": "test-key"}, CLAIMS)
    _refused(_verifier()[0], token, "ES256.*only RS256")


def test_wrong_key_is_refused():
    verifier, _, _ = _verifier(jwks(jwk(n=OTHER_N)))
    _refused(verifier, signed_jwt(CLAIMS), "signature")


def test_short_modulus_is_refused():
    verifier, _, _ = _verifier(jwks(jwk(n=SHORT_N)))
    _refused(verifier, signed_jwt(CLAIMS), "2048")


def test_signature_of_wrong_length_is_refused():
    head, body, sig = signed_jwt(CLAIMS).split(".")
    raw = base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4))
    verifier = _verifier()[0]
    for wrong in (raw[1:], bytes(1) + raw):
        _refused(verifier, f"{head}.{body}.{b64url(wrong)}", "length")


def test_unknown_kid_refetches_once_then_refuses():
    verifier, http, clock = _verifier()
    verifier.verify(signed_jwt(CLAIMS), JWKS_URI)
    clock.now += 61
    _refused(verifier, signed_jwt(CLAIMS, kid="rotated"), "rotated")
    assert http.fetches == [JWKS_URI, JWKS_URI]


def test_unknown_kid_is_found_after_the_refetch():
    verifier, http, clock = _verifier(jwks(), jwks(jwk(), jwk(kid="rotated")))
    verifier.verify(signed_jwt(CLAIMS), JWKS_URI)
    clock.now += 61
    verifier.verify(signed_jwt(CLAIMS, kid="rotated"), JWKS_URI)
    assert len(http.fetches) == 2


def test_refetch_is_rate_limited_by_the_clock():
    verifier, http, clock = _verifier()
    verifier.verify(signed_jwt(CLAIMS), JWKS_URI)
    for _ in range(3):
        clock.now += 10
        _refused(verifier, signed_jwt(CLAIMS, kid="rotated"), "rotated")
    assert http.fetches == [JWKS_URI]
    clock.now += 31
    _refused(verifier, signed_jwt(CLAIMS, kid="rotated"), "rotated")
    assert http.fetches == [JWKS_URI, JWKS_URI]


def test_missing_jwks_uri_fails_closed():
    verifier, http, _ = _verifier()
    with pytest.raises(OIDCError, match="jwks_uri"):
        verifier.verify(signed_jwt(CLAIMS), None)
    assert http.fetches == []


def test_malformed_token_is_refused():
    verifier = _verifier()[0]
    for token in (None, "", "a.b", "a.b.c.d", "!!.e30.AA"):
        _refused(verifier, token, "malformed")


def test_crit_header_is_refused():
    token = sign_rs256({"alg": "RS256", "kid": "test-key", "crit": ["exp"]}, CLAIMS)
    _refused(_verifier()[0], token, "crit")


def test_jwks_fetch_failure_fails_closed():
    class Down:
        def get_json(self, url):
            raise OSError("connection refused")

    with pytest.raises(OIDCError, match="JWKS"):
        JwksVerifier(Down(), FakeClock()).verify(signed_jwt(CLAIMS), JWKS_URI)
