"""require_https: OIDC URLs must be https, or http on a loopback host."""
import pytest

from vmn_exp.ui.auth.oidc import OIDCError, require_https


@pytest.mark.parametrize("url", [
    "https://idp.example",
    "https://idp.example:8443/realms/x",
    "HTTPS://idp.example/token",
])
def test_require_https_accepts_https(url):
    assert require_https(url, "issuer") == url


@pytest.mark.parametrize("url", [
    "http://localhost:8080",
    "http://127.0.0.1:9000/token",
    "http://127.1.2.3/",
    "http://[::1]:5556/dex",
])
def test_require_https_accepts_loopback_http(url):
    assert require_https(url, "issuer") == url


@pytest.mark.parametrize("url", [
    "http://idp.example",
    "http://10.0.0.5/token",
    "http://localhost.evil.example/",
    "ftp://idp.example",
    "idp.example",
    "",
    None,
])
def test_require_https_refuses_http_and_other_schemes(url):
    with pytest.raises(OIDCError) as e:
        require_https(url, "token_endpoint")
    assert "token_endpoint" in str(e.value) and "loopback" in str(e.value)
