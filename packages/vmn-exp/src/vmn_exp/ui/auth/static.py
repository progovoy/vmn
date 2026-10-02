#!/usr/bin/env python3
"""The standalone ``--token`` / ``VMN_UI_TOKEN`` credential: an implicit admin."""
from vmn_exp.ui.auth.principal import ADMIN, ALL_WORKSPACES, Principal
from vmn_exp.ui.middleware import bearer_matches

STATIC_PRINCIPAL = Principal("static-token", "static token", {ALL_WORKSPACES: ADMIN})


class StaticTokenAuthenticator:
    def __init__(self, token):
        self.token = token

    def authenticate(self, request):
        if bearer_matches(request.headers.get("Authorization"), self.token):
            return STATIC_PRINCIPAL
        return None
