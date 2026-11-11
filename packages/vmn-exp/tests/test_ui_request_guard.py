"""RequestGuard covers /api, /metrics and /auth; the SPA and bundle stay open.

Pure: RequestGuard.build + reject_reason, no app, no IO.
"""
from vmn_exp.ui.security import RequestGuard

REBOUND = {"host": "attacker.example"}
CROSS_SITE = {"host": "127.0.0.1:8265", "origin": "https://evil.example"}


def test_metrics_refuses_unknown_host_without_token():
    guard = RequestGuard.build()
    assert guard.reject_reason("GET", "/metrics", REBOUND) == (403, "Host not allowed")


def test_metrics_allowed_with_token_any_host():
    guard = RequestGuard.build(token_required=True)
    assert guard.reject_reason("GET", "/metrics", REBOUND) is None


def test_cross_site_post_to_auth_logout_refused():
    guard = RequestGuard.build(token_required=True)
    assert guard.reject_reason("POST", "/auth/logout", CROSS_SITE) == (
        403,
        "Cross-site request refused",
    )


def test_logout_without_content_type_allowed():
    guard = RequestGuard.build(token_required=True)
    same_site = {"host": "127.0.0.1:8265", "origin": "http://127.0.0.1:8265"}
    assert guard.reject_reason("POST", "/auth/logout", same_site) is None


def test_spa_paths_stay_unguarded():
    guard = RequestGuard.build()
    for path in ("/", "/runs/my_app", "/assets/index.js", "/index.html"):
        assert guard.reject_reason("GET", path, REBOUND) is None
