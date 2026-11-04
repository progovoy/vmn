"""A forked child on macOS never asks the system for its proxies.

botocore resolves proxies with urllib's ``getproxies``/``proxy_bypass``
(:func:`botocore.utils.get_environ_proxies`: building a client's endpoint and
the credential chain's metadata fetcher). Without a ``*_proxy`` variable set,
on macOS they ask SystemConfiguration (``_scproxy``), which is not fork-safe:
a forked child calling it segfaults. So the parent keeps the proxies botocore
resolved when it built a client (no lookup of its own), the child passes them
to botocore explicitly (``Config(proxies=...)``: botocore then skips the
lookup), and botocore's other lookups in the child read the environment only.
Elsewhere nothing changes.
"""
import functools
import sys
import urllib.request


def child_factory(build, endpoint_url, client):
    """``build(endpoint_url)`` for a forked child of this process, which built
    *client* with it."""
    if sys.platform != "darwin":
        return functools.partial(build, endpoint_url)
    return functools.partial(_child_build, build, endpoint_url, _resolved_proxies(client))


def _resolved_proxies(client):
    """The proxies botocore resolved for *client* (``get_environ_proxies``
    of its endpoint) when it built it — private botocore state, so None when
    a botocore lays it out differently: the child then resolves them from
    the environment alone (:func:`environment_proxies_only`)."""
    try:
        return client._endpoint.http_session._proxy_config._proxies
    except AttributeError:
        return None


def _child_build(build, endpoint_url, proxies):
    environment_proxies_only()
    return build(endpoint_url, proxies=proxies)


def environment_proxies_only():
    """In a forked child on macOS: botocore's proxy lookups read the
    environment, never the system's settings."""
    if sys.platform != "darwin":
        return
    import botocore.utils

    botocore.utils.getproxies = urllib.request.getproxies_environment
    botocore.utils.proxy_bypass = urllib.request.proxy_bypass_environment
