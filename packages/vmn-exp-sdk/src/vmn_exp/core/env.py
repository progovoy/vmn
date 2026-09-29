"""Stdlib-only environment capture for experiment provenance.

``capture_env()``     -> full dict (python/platform/hostname/packages/cuda/container)
``scan_packages()``   -> (dict name->version, truncated_flag) scanning sys.path
``env_summary()``     -> <= 2 KB dict suitable for metadata.yml
``packages_sha()``    -> stable sha256 over sorted name==version pairs
``_cuda_info()``      -> reads torch.version.cuda ONLY if torch already loaded
``_container_info()`` -> image digest from env vars / /.dockerenv presence
``env_from_interpreter()`` -> probe an external Python exe, parse JSON from stdout

No third-party imports; safe to run as a subprocess script.
"""
import hashlib
import importlib
import json
import os
import platform
import re
import socket
import subprocess
import sys

_PACKAGE_CAP = 2000
_PEP503_RE = re.compile(r"[-_.]+")

# Key ML packages shown verbatim in the summary.
_KEY_PACKAGES = {"torch", "tensorflow", "jax", "numpy", "transformers"}


# ---------------------------------------------------------------------------
# Name normalisation (PEP 503)
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    return _PEP503_RE.sub("-", name).lower()


# ---------------------------------------------------------------------------
# Metadata file parser
# ---------------------------------------------------------------------------

def _parse_metadata_file(path: str):
    """Return (name, version) from a METADATA or PKG-INFO file header section."""
    name = version = None
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\r\n")
                if not line:
                    break
                if line.startswith("Name:") and name is None:
                    name = line[5:].strip()
                elif line.startswith("Version:") and version is None:
                    version = line[8:].strip()
                if name and version:
                    break
    except OSError:
        pass
    return name, version


def _parse_dir_stem(stem: str):
    """Fallback: parse name and version from a dist/egg dir stem like 'numpy-1.24.0'."""
    m = re.match(r"^(.+?)-(\d[\w.]*)(.*)$", stem)
    if m:
        tail = (m.group(2) + m.group(3)).rstrip("-")
        return m.group(1), tail
    return stem, "unknown"


# ---------------------------------------------------------------------------
# Package scanning
# ---------------------------------------------------------------------------

def scan_packages(paths=None):
    """Scan *paths* (default: sys.path) for dist-info / egg-info records.

    Returns ``(packages, truncated)`` where *packages* maps normalised package
    names to version strings and *truncated* is ``True`` when the cap was hit.
    """
    if paths is None:
        paths = sys.path
    packages: dict = {}
    for base in paths:
        if not base or not os.path.isdir(base):
            continue
        try:
            entries = os.listdir(base)
        except OSError:
            continue
        for entry in entries:
            if len(packages) >= _PACKAGE_CAP:
                return packages, True
            name = version = None
            full = os.path.join(base, entry)
            if entry.endswith(".dist-info"):
                meta = os.path.join(full, "METADATA")
                if os.path.isfile(meta):
                    name, version = _parse_metadata_file(meta)
                if not name:
                    name, version = _parse_dir_stem(entry[: -len(".dist-info")])
            elif entry.endswith(".egg-info"):
                if os.path.isdir(full):
                    meta = os.path.join(full, "PKG-INFO")
                else:
                    meta = full  # single-file .egg-info
                if os.path.isfile(meta):
                    name, version = _parse_metadata_file(meta)
                if not name:
                    name, version = _parse_dir_stem(entry[: -len(".egg-info")])
            if name:
                norm = _normalize_name(name)
                packages.setdefault(norm, version or "unknown")
    return packages, False


# ---------------------------------------------------------------------------
# SHA over package list
# ---------------------------------------------------------------------------

def packages_sha(packages: dict) -> str:
    """Return a stable sha256 hex digest over sorted ``name==version`` pairs."""
    items = sorted(f"{k}=={v}" for k, v in packages.items())
    return hashlib.sha256("\n".join(items).encode()).hexdigest()


# ---------------------------------------------------------------------------
# CUDA info (never imports torch; reads it only if already loaded)
# ---------------------------------------------------------------------------

def _cuda_info():
    """Return cuda/driver info dict, or ``None`` if nothing is available."""
    result: dict = {}
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            cuda_ver = torch.version.cuda
            if cuda_ver is not None:
                result["torch_cuda"] = cuda_ver
        except Exception:
            pass

    pynvml = sys.modules.get("pynvml")
    if pynvml is None:
        try:
            pynvml = importlib.import_module("pynvml")
        except Exception:
            pass
    if pynvml is not None:
        try:
            pynvml.nvmlInit()
            result["driver"] = pynvml.nvmlSystemGetDriverVersion()
        except Exception:
            pass
    return result or None


# ---------------------------------------------------------------------------
# Container / image info (env vars only — never dumps full environ)
# ---------------------------------------------------------------------------

_DIGEST_ENV_VARS = (
    "VMN_IMAGE_DIGEST",
    "IMAGE_DIGEST",
    "DOCKER_IMAGE_DIGEST",
    "CONTAINER_IMAGE_DIGEST",
)


def _container_info():
    """Return container info dict, or ``None`` if no evidence of a container."""
    result: dict = {}
    for var in _DIGEST_ENV_VARS:
        val = os.environ.get(var)
        if val:
            result["image_digest"] = val
            break
    if os.path.exists("/.dockerenv"):
        result["in_docker"] = True
    return result or None


# ---------------------------------------------------------------------------
# Full env capture
# ---------------------------------------------------------------------------

def capture_env() -> dict:
    """Return a full environment dict (python/platform/hostname/packages/cuda/container)."""
    packages, truncated = scan_packages()
    env: dict = {
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
        },
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "release": platform.release(),
        },
        "hostname": socket.gethostname(),
        "packages": packages,
    }
    if truncated:
        env["packages_truncated"] = True
    cuda = _cuda_info()
    if cuda:
        env["cuda"] = cuda
    container = _container_info()
    if container:
        env["container"] = container
    return env


# ---------------------------------------------------------------------------
# Summary (<= 2 KB)
# ---------------------------------------------------------------------------

def env_summary(env: dict) -> dict:
    """Return a compact (<= 2 KB) summary dict suitable for metadata.yml."""
    packages = env.get("packages", {})
    key_pkgs = {k: packages[k] for k in _KEY_PACKAGES if k in packages}
    summary: dict = {
        "python": env.get("python", {}).get("version"),
        "platform": "{}/{}".format(
            env.get("platform", {}).get("system", ""),
            env.get("platform", {}).get("machine", ""),
        ),
        "packages_count": len(packages),
        "packages_sha": packages_sha(packages),
    }
    if key_pkgs:
        summary["key_packages"] = key_pkgs
    cuda = env.get("cuda")
    if cuda:
        summary["cuda"] = cuda
    container = env.get("container")
    if container and container.get("image_digest"):
        summary["image_digest"] = container["image_digest"]
    return summary


# ---------------------------------------------------------------------------
# Probe an external interpreter
# ---------------------------------------------------------------------------

def env_from_interpreter(python_exe: str, timeout: int = 5) -> dict:
    """Run this module file under *python_exe* with ``-I`` and return the JSON output.

    The child runs in isolated mode so it does not inherit PYTHONPATH or
    site-packages from the caller.  If the child does not have vmn installed,
    we still run the raw file (it is stdlib-only and has no imports from vmn).
    """
    module_file = os.path.abspath(__file__)
    result = subprocess.run(
        [python_exe, "-I", module_file],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"env_from_interpreter failed (exit {result.returncode}): {result.stderr}"
        )
    return json.loads(result.stdout)


# ---------------------------------------------------------------------------
# Capture-decision helpers
# ---------------------------------------------------------------------------

#: Environment variable that opts out of env capture when set to ``0`` or
#: a falsy string (``false``, ``no``, ``off``).
CAPTURE_ENV_ENV = "VMN_CAPTURE_ENV"

_OPT_OUT_VALS = frozenset(("0", "false", "False", "no", "off"))


def opted_in(explicit, env_var, conf_key, exp_conf=None):
    """Whether an on-by-default feature is on.

    Precedence: explicit arg > *env_var* > ``exp_conf[conf_key]`` > True.

    *explicit* controls the override:

    * ``False`` — always off (overrides env-var and conf).
    * ``True``  — override conf, but still respect *env_var*.
    * ``None``  — full opt-out chain (env-var → conf → default True).

    *exp_conf* is the ``experiment:`` section of the app's conf.yml, as a dict.
    """
    if explicit is False:
        return False
    if os.environ.get(env_var) in _OPT_OUT_VALS:
        return False
    if explicit is True:
        return True
    conf_val = (exp_conf or {}).get(conf_key)
    if conf_val is not None:
        return bool(conf_val)
    return True


def should_capture(explicit, exp_conf=None):
    """Return True if the environment should be captured (see :func:`opted_in`)."""
    return opted_in(explicit, CAPTURE_ENV_ENV, "capture_env", exp_conf)


def capture_env_safe(python_exe=None):
    """Capture the environment dict; return ``None`` on any failure (never raises).

    When *python_exe* is given the child interpreter is probed via
    ``env_from_interpreter``; otherwise the current interpreter is captured.
    """
    try:
        if python_exe:
            return env_from_interpreter(python_exe, timeout=5)
        return capture_env()
    except Exception:
        import logging

        logging.getLogger(__name__).warning(
            "vmn: could not capture environment for this run"
        )
        return None


# ---------------------------------------------------------------------------
# __main__: print JSON for env_from_interpreter / manual use
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(json.dumps(capture_env()))
