"""``vmn-exp login --server <url>``: the OIDC device flow through a vmn-exp server.

The server runs the flow against its IdP and answers with a vmn API token,
kept in ``~/.config/vmn-exp/credentials`` (``$XDG_CONFIG_HOME`` honoured;
mode 0600) for CLI commands that call the server API. Jobs never need it.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

TIMEOUT_SEC = 30
PENDING = ("authorization_pending", "slow_down")


def credentials_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "vmn-exp", "credentials")


def _server_key(server):
    return server.rstrip("/")


def _read_credentials():
    try:
        with open(credentials_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"servers": {}}


def save_token(server, token, expires_at=0):
    creds = _read_credentials()
    creds.setdefault("servers", {})[_server_key(server)] = {
        "token": token, "expires_at": expires_at}
    path = credentials_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(creds, f, indent=2)
    os.replace(tmp, path)


def load_token(server):
    entry = _read_credentials().get("servers", {}).get(_server_key(server))
    return entry["token"] if entry else None


def urllib_post_json(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.load(exc)
        except ValueError:
            return exc.code, {"detail": exc.reason}


def _poll(server, start, post_json, sleep):
    interval = max(0, int(start.get("interval", 5)))
    deadline = time.monotonic() + int(start.get("expires_in", 600))
    while time.monotonic() < deadline:
        sleep(interval)
        status, body = post_json(f"{server}/auth/device/token",
                                 {"device_code": start["device_code"]})
        if status == 200:
            return body, None
        error = body.get("error") or body.get("detail") or f"HTTP {status}"
        if error not in PENDING:
            return None, error
        if error == "slow_down":
            interval += 5
    return None, "expired_token"


def login(server, post_json=urllib_post_json, sleep=time.sleep, say=print):
    server = _server_key(server)
    status, start = post_json(f"{server}/auth/device/start", {})
    if status != 200:
        say(f"Login failed: {start.get('detail') or start.get('error') or status}")
        return 1
    url = start.get("verification_uri_complete") or start.get("verification_uri")
    say(f"Open {url} and enter the code {start.get('user_code')}")
    body, error = _poll(server, start, post_json, sleep)
    if error:
        say(f"Login failed: {error}")
        return 1
    save_token(server, body["token"], body.get("expires_at", 0))
    say(f"Logged in to {server}; token saved in {credentials_path()}")
    return 0


def run_login(argv):
    parser = argparse.ArgumentParser(prog="vmn-exp login", description=__doc__.split("\n")[0])
    parser.add_argument("--server", required=True, help="the vmn-exp server URL")
    args = parser.parse_args(argv)
    return login(args.server, say=lambda msg: print(msg, file=sys.stderr))
