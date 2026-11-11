#!/usr/bin/env python3
"""RS256 id_token signatures checked against the IdP's JWKS, standard library only.

RS256 is RSASSA-PKCS1-v1_5 with SHA-256 (RFC 7518 3.3). Verification follows
RFC 8017 8.2.2: the signature must be exactly as long as the modulus and
smaller than it; ``s^e mod n`` is turned back into bytes and compared, in
constant time, with the EMSA-PKCS1-v1_5 encoding built here from the SHA-256
of the signing input. The decrypted block is never parsed. Any other alg
(``none``, ES256, PS256...) and any ``crit`` header (RFC 7515 4.1.11) are
refused, and keys under 2048 bits are refused.
"""
import base64
import binascii
import hashlib
import hmac
import json

from vmn_exp.ui.auth.oidc import OIDCError

ALG = "RS256"
MIN_MODULUS_BITS = 2048
REFETCH_INTERVAL_SEC = 60
# DER DigestInfo prefix for SHA-256 (RFC 8017 section 9.2, note 1).
SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


def _b64url_decode(text):
    if not isinstance(text, str) or not text.isascii():
        raise ValueError("not base64url")
    padded = text.translate(str.maketrans("-_", "+/")) + "=" * (-len(text) % 4)
    return base64.b64decode(padded, validate=True)


def _b64url_int(text):
    return int.from_bytes(_b64url_decode(text), "big")


def _split(id_token):
    """``(header dict, signing input bytes, signature bytes)`` of a compact JWS."""
    try:
        head, body, sig = id_token.split(".")
        header = json.loads(_b64url_decode(head))
        signature = _b64url_decode(sig)
    except (AttributeError, ValueError, binascii.Error) as exc:
        raise OIDCError("malformed id_token") from exc
    if not isinstance(header, dict):
        raise OIDCError("malformed id_token")
    return header, f"{head}.{body}".encode(), signature


def _check_header(header):
    alg = header.get("alg")
    if alg != ALG:
        raise OIDCError(f"id_token alg {alg!r} is not supported: only {ALG} is accepted")
    if "crit" in header:
        raise OIDCError("id_token has a crit header, which is not supported")


def _emsa_pkcs1_v1_5_sha256(message, k):
    """EMSA-PKCS1-v1_5 encoding (RFC 8017 9.2) of *message* in *k* bytes."""
    t = SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    return b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t


def _verify_rsa(key, signing_input, signature):
    try:
        n, e = _b64url_int(key["n"]), _b64url_int(key["e"])
    except (KeyError, ValueError, binascii.Error) as exc:
        raise OIDCError("malformed JWKS key") from exc
    if n.bit_length() < MIN_MODULUS_BITS:
        raise OIDCError(f"JWKS key modulus is under {MIN_MODULUS_BITS} bits")
    if e < 3 or e % 2 == 0:
        raise OIDCError("JWKS key has an invalid public exponent")
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        raise OIDCError("id_token signature length does not match the key")
    s = int.from_bytes(signature, "big")
    if s >= n:
        raise OIDCError("id_token signature is invalid")
    em = pow(s, e, n).to_bytes(k, "big")
    if not hmac.compare_digest(em, _emsa_pkcs1_v1_5_sha256(signing_input, k)):
        raise OIDCError("id_token signature is invalid")


class JwksVerifier:
    """Checks an id_token's RS256 signature; *http* has ``get_json(url)``,
    *clock* returns seconds. An unknown ``kid`` re-fetches the JWKS at most
    once per :data:`REFETCH_INTERVAL_SEC`."""

    def __init__(self, http, clock):
        self.http = http
        self.clock = clock
        self._keys = {}  # jwks_uri -> (fetched at, [jwk])

    def verify(self, id_token, jwks_uri):
        """Returns nothing; raises :class:`OIDCError` unless the signature holds."""
        if not jwks_uri:
            raise OIDCError("the identity provider's discovery document has no jwks_uri")
        header, signing_input, signature = _split(id_token)
        _check_header(header)
        _verify_rsa(self._key(jwks_uri, header.get("kid")), signing_input, signature)

    def _key(self, jwks_uri, kid):
        cached = self._keys.get(jwks_uri)
        if cached is None or (_find(cached[1], kid) is None
                              and self.clock() - cached[0] >= REFETCH_INTERVAL_SEC):
            cached = self._fetch(jwks_uri)
        key = _find(cached[1], kid)
        if key is None:
            raise OIDCError(f"no RSA signing key with kid {kid!r} in the JWKS")
        return key

    def _fetch(self, jwks_uri):
        now = self.clock()
        try:
            keys = self.http.get_json(jwks_uri)["keys"]
        except Exception as exc:
            raise OIDCError("JWKS fetch failed") from exc
        self._keys[jwks_uri] = (now, keys if isinstance(keys, list) else [])
        return self._keys[jwks_uri]


def _find(keys, kid):
    for key in keys:
        if (isinstance(key, dict) and key.get("kty") == "RSA" and key.get("kid") == kid
                and key.get("use", "sig") == "sig"):
            return key
    return None
