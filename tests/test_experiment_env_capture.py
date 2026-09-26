"""Tests for version_stamp.core.experiment_env — stdlib-only env capture.

No git, no docker, no storage.  All tests are pure unit/integration tests that
run without Docker (pytest-xdist compatible).
"""
import ast
import importlib
import json
import os
import sys
import sysconfig
import tempfile
import time
import types

import pytest


# ---------------------------------------------------------------------------
# Basic capture shape
# ---------------------------------------------------------------------------

def test_capture_has_python_platform_packages():
    from version_stamp.core.experiment_env import capture_env

    env = capture_env()
    assert "python" in env
    assert "version" in env["python"]
    assert "implementation" in env["python"]
    assert "executable" in env["python"]
    assert "platform" in env
    assert "system" in env["platform"]
    assert "machine" in env["platform"]
    assert "hostname" in env
    assert "packages" in env
    assert isinstance(env["packages"], dict)
    assert len(env["packages"]) > 0


# ---------------------------------------------------------------------------
# Package scanning vs importlib.metadata
# ---------------------------------------------------------------------------

def test_packages_match_importlib_metadata():
    """scan_packages() should find at least a subset of importlib.metadata packages."""
    from version_stamp.core.experiment_env import scan_packages

    packages, _truncated = scan_packages()
    # importlib.metadata should be available (Python 3.8+)
    import importlib.metadata as im
    # Pick a package we know is installed in the test venv
    known = None
    for dist in im.distributions():
        try:
            name = dist.metadata["Name"]
            ver = dist.metadata["Version"]
            if name and ver:
                known = (name.lower(), ver)
                break
        except Exception:
            continue
    assert known is not None, "importlib.metadata found no packages"
    # Normalize and check
    norm_name = known[0].replace("_", "-").replace(".", "-")
    assert norm_name in packages or known[0].replace("_", "-") in packages, (
        f"scan_packages missed {known[0]} (looked up as {norm_name})"
    )


# ---------------------------------------------------------------------------
# Performance
# ---------------------------------------------------------------------------

def test_capture_under_50ms():
    """capture_env() must complete in under 50 ms (take best of 5 runs)."""
    from version_stamp.core.experiment_env import capture_env

    times = []
    for _ in range(5):
        t0 = time.perf_counter()
        capture_env()
        times.append(time.perf_counter() - t0)
    best = min(times)
    assert best < 0.05, f"capture_env best time {best*1000:.1f}ms exceeds 50ms"


# ---------------------------------------------------------------------------
# Never imports torch
# ---------------------------------------------------------------------------

def test_never_imports_torch():
    """capture_env() must not import torch even when it's not installed."""
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys;"
                "from version_stamp.core.experiment_env import capture_env;"
                "capture_env();"
                "print('torch' in sys.modules)"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "False", "capture_env imported torch"


# ---------------------------------------------------------------------------
# CUDA info reads torch.version.cuda without device queries
# ---------------------------------------------------------------------------

def test_torch_cuda_read_without_device_queries():
    """_cuda_info reads torch.version.cuda if torch is already in sys.modules."""
    from version_stamp.core import experiment_env

    fake_version = types.SimpleNamespace(cuda="12.1")
    fake_torch = types.SimpleNamespace(version=fake_version)

    old = sys.modules.get("torch", _MISSING := object())
    sys.modules["torch"] = fake_torch
    try:
        info = experiment_env._cuda_info()
    finally:
        if old is _MISSING:
            del sys.modules["torch"]
        else:
            sys.modules["torch"] = old

    assert info is not None
    assert info.get("torch_cuda") == "12.1"


def test_cuda_info_absent_when_torch_not_loaded():
    """_cuda_info returns nothing (no torch_cuda key) when torch not in sys.modules."""
    from version_stamp.core import experiment_env

    old = sys.modules.pop("torch", None)
    try:
        info = experiment_env._cuda_info()
    finally:
        if old is not None:
            sys.modules["torch"] = old

    # Without torch, there should be no torch_cuda key
    assert info is None or "torch_cuda" not in info


# ---------------------------------------------------------------------------
# pynvml driver
# ---------------------------------------------------------------------------

def test_pynvml_driver_with_fake_module():
    """_cuda_info uses pynvml driver version when pynvml is importable."""
    from version_stamp.core import experiment_env

    # Build a fake pynvml that returns a known driver version
    fake_pynvml = types.ModuleType("pynvml")
    fake_pynvml.nvmlInit = lambda: None
    fake_pynvml.nvmlSystemGetDriverVersion = lambda: "525.105.17"

    old_pynvml = sys.modules.get("pynvml", None)
    # Remove torch so it doesn't interfere
    old_torch = sys.modules.pop("torch", None)
    sys.modules["pynvml"] = fake_pynvml
    try:
        info = experiment_env._cuda_info()
    finally:
        if old_pynvml is None:
            sys.modules.pop("pynvml", None)
        else:
            sys.modules["pynvml"] = old_pynvml
        if old_torch is not None:
            sys.modules["torch"] = old_torch

    assert info is not None
    assert info.get("driver") == "525.105.17"


# ---------------------------------------------------------------------------
# Container info from env vars
# ---------------------------------------------------------------------------

def test_image_digest_from_env():
    from version_stamp.core.experiment_env import _container_info

    for var in ("VMN_IMAGE_DIGEST", "IMAGE_DIGEST", "DOCKER_IMAGE_DIGEST",
                "CONTAINER_IMAGE_DIGEST"):
        old = os.environ.pop(var, None)
        try:
            os.environ[var] = "sha256:abc123"
            info = _container_info()
        finally:
            if old is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = old

        assert info is not None, f"{var} not picked up"
        assert info.get("image_digest") == "sha256:abc123", f"{var}: {info}"


# ---------------------------------------------------------------------------
# Env vars not dumped
# ---------------------------------------------------------------------------

def test_env_vars_not_dumped():
    """capture_env() must not include os.environ values in its output."""
    from version_stamp.core.experiment_env import capture_env

    # Plant a detectable secret in the environment
    os.environ["VMN_TEST_SECRET_XYZ"] = "super-secret-value-9827364"
    try:
        env = capture_env()
        # Serialize and check
        raw = json.dumps(env)
        assert "super-secret-value-9827364" not in raw
    finally:
        del os.environ["VMN_TEST_SECRET_XYZ"]


# ---------------------------------------------------------------------------
# Summary: size and stability
# ---------------------------------------------------------------------------

def test_summary_small_and_sha_stable():
    from version_stamp.core.experiment_env import capture_env, env_summary, packages_sha

    env = capture_env()
    summary = env_summary(env)

    # Must be serializable to <= 2048 bytes
    raw = json.dumps(summary, separators=(",", ":"))
    assert len(raw.encode()) <= 2048, f"summary too large: {len(raw)} bytes"

    # SHA must be stable across two calls with the same packages
    sha1 = packages_sha(env["packages"])
    sha2 = packages_sha(env["packages"])
    assert sha1 == sha2
    assert len(sha1) == 64  # sha256 hex


# ---------------------------------------------------------------------------
# Package list capped
# ---------------------------------------------------------------------------

def test_package_list_capped():
    """scan_packages respects the 2000-package cap and sets truncated flag."""
    from version_stamp.core import experiment_env

    orig_cap = experiment_env._PACKAGE_CAP
    try:
        # Lower the cap to something tiny
        experiment_env._PACKAGE_CAP = 3
        packages, truncated = environment_env_scan_with_many_packages(experiment_env)
    finally:
        experiment_env._PACKAGE_CAP = orig_cap

    assert len(packages) <= 3
    assert truncated is True


def environment_env_scan_with_many_packages(experiment_env):
    """Helper: scan with a fake directory that has many dist-info entries."""
    with tempfile.TemporaryDirectory() as td:
        for i in range(10):
            di = os.path.join(td, f"pkg{i}-1.0.0.dist-info")
            os.makedirs(di)
            with open(os.path.join(di, "METADATA"), "w") as f:
                f.write(f"Name: pkg{i}\nVersion: 1.0.0\n\n")
        return experiment_env.scan_packages(paths=[td])


# ---------------------------------------------------------------------------
# dist-info and egg-info parsing
# ---------------------------------------------------------------------------

def test_dist_info_egg_info_parsing():
    from version_stamp.core.experiment_env import scan_packages

    with tempfile.TemporaryDirectory() as td:
        # dist-info style
        di = os.path.join(td, "mylib-2.3.4.dist-info")
        os.makedirs(di)
        with open(os.path.join(di, "METADATA"), "w") as f:
            f.write("Name: mylib\nVersion: 2.3.4\n\nDescription follows.\n")

        # egg-info dir style
        ei = os.path.join(td, "otherlib-1.0.0.egg-info")
        os.makedirs(ei)
        with open(os.path.join(ei, "PKG-INFO"), "w") as f:
            f.write("Name: otherlib\nVersion: 1.0.0\n\n")

        packages, _ = scan_packages(paths=[td])

    assert "mylib" in packages, f"mylib not in {list(packages)}"
    assert packages["mylib"] == "2.3.4"
    assert "otherlib" in packages, f"otherlib not in {list(packages)}"
    assert packages["otherlib"] == "1.0.0"


# ---------------------------------------------------------------------------
# Unparseable dir falls back to dir name
# ---------------------------------------------------------------------------

def test_unparseable_dir_falls_back():
    from version_stamp.core.experiment_env import scan_packages

    with tempfile.TemporaryDirectory() as td:
        # METADATA with no Name/Version headers
        di = os.path.join(td, "weirdpkg-0.9.dist-info")
        os.makedirs(di)
        with open(os.path.join(di, "METADATA"), "w") as f:
            f.write("Some-Other-Header: value\n\n")

        packages, _ = scan_packages(paths=[td])

    # Should have fallen back to parsing the dir name "weirdpkg-0.9"
    assert "weirdpkg" in packages, f"fallback failed; packages={list(packages)}"


# ---------------------------------------------------------------------------
# Runs as a script (isolated mode)
# ---------------------------------------------------------------------------

def test_runs_as_script_isolated():
    """`python -I /path/to/experiment_env.py` prints valid JSON with required keys."""
    import subprocess

    module_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "version_stamp", "core", "experiment_env.py",
    )
    assert os.path.isfile(module_file), f"Module not found: {module_file}"

    result = subprocess.run(
        [sys.executable, "-I", module_file],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, f"Script failed: {result.stderr}"
    data = json.loads(result.stdout)
    assert "python" in data
    assert "packages" in data


# ---------------------------------------------------------------------------
# Stdlib-only imports (AST check)
# ---------------------------------------------------------------------------

def _get_stdlib_names():
    """Return a set of known stdlib module names (works on Python 3.9+)."""
    # Python 3.10+ has sys.stdlib_module_names
    if hasattr(sys, "stdlib_module_names"):
        return set(sys.stdlib_module_names)
    # Fallback: scan the stdlib directory + builtin modules
    stdlib_dir = sysconfig.get_paths()["stdlib"]
    import pkgutil
    names = set(sys.builtin_module_names)
    for _finder, name, _ispkg in pkgutil.iter_modules([stdlib_dir]):
        names.add(name)
    # Also add lib-dynload
    dynload = os.path.join(stdlib_dir, "lib-dynload")
    if os.path.isdir(dynload):
        for _finder, name, _ispkg in pkgutil.iter_modules([dynload]):
            names.add(name)
    # Standard sub-packages not discovered by iter_modules
    names.update({"os", "os.path", "email", "email.mime", "importlib",
                   "importlib.util", "importlib.metadata", "collections",
                   "collections.abc", "concurrent", "concurrent.futures",
                   "unittest", "unittest.mock", "logging", "logging.handlers",
                   "urllib", "urllib.parse", "urllib.request", "urllib.error",
                   "http", "http.client", "html", "html.parser", "xml",
                   "xml.etree", "xml.etree.ElementTree", "contextlib",
                   "dataclasses", "typing", "types", "functools", "itertools",
                   "operator", "copy", "pathlib", "tempfile", "shutil",
                   "subprocess", "threading", "multiprocessing", "socket",
                   "ssl", "struct", "io", "abc", "enum", "weakref",
                   "traceback", "inspect", "dis", "ast", "textwrap",
                   "string", "re", "fnmatch", "glob", "stat",
                   "hashlib", "hmac", "secrets", "base64", "binascii",
                   "json", "csv", "configparser", "argparse",
                   "datetime", "time", "calendar", "math", "random",
                   "decimal", "fractions", "statistics",
                   "platform", "sysconfig", "pkgutil", "zipimport",
                   "_thread", "__future__"})
    return names


def test_stdlib_only_imports():
    """AST-parse experiment_env.py: every top-level import must be stdlib."""
    module_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "version_stamp", "core", "experiment_env.py",
    )
    assert os.path.isfile(module_path), f"Module not found: {module_path}"

    with open(module_path, encoding="utf-8") as f:
        source = f.read()

    tree = ast.parse(source)
    stdlib_names = _get_stdlib_names()

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in stdlib_names:
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if node.level == 0 and top not in stdlib_names:
                    violations.append(f"from {node.module} import ...")

    assert not violations, f"Non-stdlib imports found: {violations}"
