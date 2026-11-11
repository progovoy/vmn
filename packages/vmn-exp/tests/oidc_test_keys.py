"""A fixed RSA test keypair for OIDC id_token tests (a helper, not a test).

Generated once offline with ``openssl genrsa 2048`` (``OTHER_N``: a second
2048-bit key, ``SHORT_N``: a 1024-bit one). ``OPENSSL_SIGNED_TOKEN`` was
signed by ``openssl dgst -sha256 -sign`` with the ``N``/``D`` key, so the
verifier is also checked against a signer other than this file's.
"""
import base64
import hashlib
import json

E = 65537
KID = "test-key"
JWKS_URI = "https://idp.example/jwks"
# DER DigestInfo prefix for SHA-256 (RFC 8017 section 9.2, note 1).
SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")

N = int(
    "c394964bc01d47d87e8ec106895ff3d02bc11526ecddb1648149e599aa46398e"
    "448d60fea2977a767cb8b69d9b9d9a3e4c6179aef53ae3d042f3f775f2813bd4"
    "de413b509d60da53713d748240bdc8324299fd7f1300db35dd348113d4f383f3"
    "211422b9cb7fd4469d6337f50ab343ba4a926bbcf9ff5a86d1cf4a1b11132b73"
    "8a29c5d6d8186108f78faa2b96a16649a013bbc936bd98de812cce7906c52241"
    "53c3883ac9b5e28acbc8fffa084208e32290440a7391d2c59a736442c591bd9c"
    "86343cbed466d6ec707d1860c31a70013014403734699bce8b0972710ab9a5b5"
    "b138c25aacac8e9f09f2fbbb12dd1a87eab3cd375c023eed947198c85d02c23d", 16)

D = int(
    "11df7140a8e4c41d07abb9fe03edcdd5173a84d952ca0b9cf8a7ad20b6cbc614"
    "b73508491cc8a4fb50f87c4fb8d9d52f9e41462273ec96c700675514e53d641f"
    "56d4353c6fb55b1e46f9ebbcbf77d864a76b751bf8bb9a4cb8d3447c70787475"
    "726f69a0faf4ca8c4d73b4b862eaf0e4844e0f246ce02600ae09b866f2cf82a7"
    "da632c7cc02a6a655271e0a59417a9896df46110a0050decad5d0d3720055372"
    "db1ac8645457c0105b10247f3cf31ad5ea8f9c83c3392ac4a4efda59f582d663"
    "91f18a03bd0b3ed54fccd5ef027e242e21127602ab2c8904dc16e69f9b99fc1b"
    "fbc7aaf41cc37c4df07a4410b5113221cd8913fba0fb66fa6250b47d1306d9cd", 16)

OTHER_N = int(
    "ca453d86aeead2fe52099f2b07a4dbe2aef5da1a65ef95fca8ef7af4c8e0bb2b"
    "a0cf90194361165ef0c778fec63191111ccc427bfa48322373f211052af5e886"
    "0d9baa0ddcf09928e5b97be44fd96168fde201caa294503cda4bb920aa793423"
    "a34d8d03747887e21a17afad1c4f42ae6f99c4f1167c3e87ca22a4c885576fdf"
    "2fa58f70da5606812f786fb273a47201023be5e71b713d59ebc0ca4f781f3539"
    "de5ac71e1e516e00051a07895a6fde77f80f8480a56954428e17bf204f72a7dc"
    "86f113d418f82e9b36a76acc1178aefa74ca7c5b280739eb4a7fe0b6007f09f5"
    "8bd86d0a52eef67008ebd7df2c30cfe1e0fcedbcce4c07b850cfaba9b23a5f2d", 16)

SHORT_N = int(
    "b577bc8231a5196f260c31804560b9fa34f603becd221d0da2a61bedb3c63002"
    "e5c9c71212ea430553a48230c67c26414d6c44416efd5b7f0d1a545105037fed"
    "da235f81e264b893a5f3667d68ca3bef0fedf63db189225a1efc4c85cf477797"
    "b7f235698abc8509be4ba976a6ee878b92cc63e8ef999eb3503800d68ab5e287", 16)

OPENSSL_SIGNED_TOKEN = (
    "eyJhbGciOiAiUlMyNTYiLCAia2lkIjogInRlc3Qta2V5IiwgInR5cCI6ICJKV1QifQ."
    "eyJpc3MiOiAiaHR0cHM6Ly9pZHAuZXhhbXBsZSIsICJzdWIiOiAidTEifQ."
    "nEDIzjOgGaiV0nornLKO4kotfAP6sdaUalE0ND5J_vCy5zklc_6H8elwvXFUIFHo"
    "aQjw8vnb8d4gHRiunc9LgPmWgL2k1Gh1KCnFIL_mLXLqLVD4lr_kSooCNzewMONo"
    "Ouo5jWnbl3NZZb_l0fkAdT-C-i3LPXLobf6QXzlcpYQSCArfxWhwNhWapnSwkgmJ"
    "DwiNnKg7461zG2RarOLYQIcs-vVPt7jHsptWJTixiHqfzF92IThSY6lgjE4_Mkzj"
    "8LUXfu6cpMgnZvm2O5XiYA9CrGfMX1FmxXbINWnCYr1q0jg9pghKOoXviVURG9i4"
    "taXF3ZDTURliA8ReqLhw6g"
)


def b64url(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _int_b64url(value):
    return b64url(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def jwk(n=N, kid=KID, e=E):
    return {"kty": "RSA", "use": "sig", "alg": "RS256", "kid": kid,
            "n": _int_b64url(n), "e": _int_b64url(e)}


def jwks(*keys):
    return {"keys": list(keys) or [jwk()]}


def sign_rs256(header, claims, d=D, n=N):
    """A compact JWS of *claims* under *header*: RSASSA-PKCS1-v1_5 with SHA-256."""
    head = b64url(json.dumps(header).encode())
    body = b64url(json.dumps(claims).encode())
    k = (n.bit_length() + 7) // 8
    t = SHA256_DIGEST_INFO + hashlib.sha256(f"{head}.{body}".encode()).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    sig = pow(int.from_bytes(em, "big"), d, n).to_bytes(k, "big")
    return f"{head}.{body}.{b64url(sig)}"


def signed_jwt(claims, kid=KID):
    return sign_rs256({"alg": "RS256", "kid": kid, "typ": "JWT"}, claims)
