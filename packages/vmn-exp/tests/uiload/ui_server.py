"""Run ``vmn-exp ui`` as a separate process over a uiload data root."""
import os
import signal
import socket
import subprocess
import sys
import time

import httpx

from uiload.probe import app_path
from uiload.worker import with_src_pythonpath

READY_TIMEOUT_SEC = 120
INDEX_TIMEOUT_SEC = 1800


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class UIServer:
    """``vmn-exp ui --repo <root>`` with the stuck floor lowered to *min_stale_sec*."""

    def __init__(self, root, run_dir, min_stale_sec, port=None):
        self.root, self.run_dir = root, run_dir
        self.port = port or free_port()
        self.base_url = f"http://127.0.0.1:{self.port}"
        self.min_stale_sec = min_stale_sec
        self.proc = None

    def start(self):
        env = with_src_pythonpath(dict(os.environ, VMN_EXP_MIN_STALE_SEC=str(self.min_stale_sec)))
        cmd = [sys.executable, "-m", "vmn_exp.cli", "ui", "--repo", self.root, "--no-browser",
               "--port", str(self.port), "--data-dir", os.path.join(self.run_dir, "uidata")]
        log = open(os.path.join(self.run_dir, "ui.log"), "ab")
        self.proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT,
                                     start_new_session=True)
        self._wait_ready()
        return self

    def _wait_ready(self):
        deadline = time.monotonic() + READY_TIMEOUT_SEC
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"vmn-exp ui exited {self.proc.returncode}; see {self.run_dir}/ui.log")
            try:
                if httpx.get(f"{self.base_url}/api/v1/meta", timeout=2).status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise TimeoutError(f"vmn-exp ui not ready after {READY_TIMEOUT_SEC}s")

    def wait_indexed(self, ws, app, total, timeout_sec=INDEX_TIMEOUT_SEC):
        """Seconds until the leaderboard lists *total* runs (``archived=1``) —
        the cold-start cost a user pays before the first page renders."""
        url = f"{self.base_url}/api/v1{app_path(ws, app)}/experiments"
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout_sec:
            try:
                body = httpx.get(url, params={"offset": 0, "limit": 1, "archived": 1},
                                 timeout=timeout_sec).json()
                if body.get("total", 0) >= total:
                    return round(time.monotonic() - t0, 2)
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.5)
        raise TimeoutError(f"{total} runs not listed after {timeout_sec}s")

    def stop(self):
        if self.proc and self.proc.poll() is None:
            os.killpg(self.proc.pid, signal.SIGTERM)
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait()
