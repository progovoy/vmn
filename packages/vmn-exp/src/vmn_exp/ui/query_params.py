#!/usr/bin/env python3
"""Unknown query parameters on the HTTP API answer 400, not a silently
unfiltered page: one app-wide dependency compares a request's params with the
ones its route declares (plan 31 §4.2). The web page is not API and keeps
whatever its URL carries."""
import difflib

from fastapi import Depends, HTTPException, Request

# The web page's own URL params (``/experiments?view=jobs``): the API has
# its own words for them.
WEB_PAGE_PARAMS = ("view", "kind", "tab", "sel")

ACCEPTED_ATTR = "vmn_query_params"  # a route's declared names, set on first use


def refuse_unknown_params(api_prefix):
    """The dependency refusing a param the matched route under *api_prefix*
    does not declare."""

    async def _refuse(request: Request):
        route = request.scope.get("route")
        if route is None or not route.path.startswith(api_prefix):
            return
        accepted = getattr(route, ACCEPTED_ATTR, None)
        if accepted is None:
            accepted = _declared(route.dependant)
            setattr(route, ACCEPTED_ATTR, accepted)
        unknown = [n for n in request.query_params if n not in accepted]
        if unknown:
            raise HTTPException(400, _reason(unknown, accepted))

    return Depends(_refuse)


def _declared(dependant):
    names = {field.alias for field in dependant.query_params}
    for sub in dependant.dependencies:
        names |= _declared(sub)
    return frozenset(names)


def _reason(unknown, accepted):
    web = next((n for n in unknown if n in WEB_PAGE_PARAMS), None)
    if web:
        return f"{web} is a web page parameter; use top=jobs or q=…"
    name = unknown[0]
    close = difflib.get_close_matches(name, accepted, n=1)
    hint = f"; did you mean '{close[0]}'?" if close else ""
    return f"Unknown query parameter '{name}'{hint}"
