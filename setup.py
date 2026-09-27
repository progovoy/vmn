import os

import setuptools

from version_stamp import version

description = "Stamping utility"

with open("README.md") as fid:
    long_description = fid.read()

# ---------------------------------------------------------------------------
# Pure helpers — factored out so tests/test_packaging_dists.py can call them
# directly without triggering a real build.
# ---------------------------------------------------------------------------

_EXP_PACKAGES = [
    # Minimal version_stamp slice: facade + its leaf deps (no GitPython).
    # version_stamp.cli is included because coldstart.py imports INIT_FILENAME
    # from version_stamp.cli.constants at module load time; cli/__init__.py is
    # lazy (PEP 562) and cli/constants.py only imports core.constants + core.models.
    "version_stamp",
    "version_stamp.core",
    "version_stamp.cli",
    # devversion is needed by vmn_exp.snapshot at import time (dev-version
    # capture/apply helpers that snapshot.__init__ re-exports).
    "version_stamp.devversion",
    # The experiment SDK and its direct dependencies.
    # vmn_exp.cli is included because sdk/create.py imports
    # _get_experiment_storage from vmn_exp.cli.experiment at module level.
    # None of vmn_exp.cli.* imports GitPython.
    "vmn_exp",
    "vmn_exp.sdk",
    "vmn_exp.cli",
    "vmn_exp.core",
    "vmn_exp.storage",
    "vmn_exp.registry",
    "vmn_exp.snapshot",
    "vmn_exp.integrations",
]

_EXP_REQUIRES = [
    "PyYAML>=5.4.1",
    "filelock>=3.2.0",
]

_EXP_EXTRAS = {
    # Slim extras mirror the full wheel's optional deps that the SDK can use
    "s3": ["boto3"],
    "sysmetrics": ["psutil>=5.9"],
    "hf": ["transformers"],
    "optuna": ["optuna"],
    "ray": ["ray[tune]"],
}


def _select_packages(dist):
    """Return the packages list for the given distribution target.

    ``dist='exp'`` → slim vmn-exp wheel (SDK + storage + registry, no stamping).
    ``dist='vmn'`` (or any other value) → full vmn wheel.
    """
    if dist == "exp":
        return list(_EXP_PACKAGES)
    return [
        "version_stamp",
        "version_stamp.compat",
        "version_stamp.core",
        "version_stamp.backends",
        "version_stamp.stamping",
        "version_stamp.cli",
        "version_stamp.devversion",
        "vmn_exp",
        "vmn_exp.sdk",
        "vmn_exp.cli",
        "vmn_exp.core",
        "vmn_exp.importers",
        "vmn_exp.integrations",
        "vmn_exp.registry",
        "vmn_exp.snapshot",
        "vmn_exp.storage",
        "vmn_exp.ui",
        "vmn_exp.ui.readers",
    ]


def _select_requires(dist):
    """Return install_requires for the given distribution target."""
    if dist == "exp":
        return list(_EXP_REQUIRES)
    with open("tests/requirements.txt") as f:
        return [
            ln.strip()
            for ln in f
            if ln.strip() and not ln.strip().startswith("#")
        ]


# ---------------------------------------------------------------------------
# Build functions — defined before dispatch so the AST reader in
# tests/test_packaging.py finds _setup_default's literal packages= first.
# ---------------------------------------------------------------------------

def _setup_default():
    """Full vmn distribution — the default when VMN_DIST is unset."""
    with open("tests/requirements.txt") as fid:
        install_requires = fid.readlines()

    setuptools.setup(
        name="vmn",
        version=version.version,
        author="Pavel Rogovoy",
        author_email="p.rogovoy@gmail.com",
        description=description,
        long_description=long_description,
        long_description_content_type="text/markdown",
        python_requires=">=3.8",
        url="https://github.com/progovoy/vmn",
        install_requires=install_requires,
        extras_require={
            "ui": ["fastapi>=0.110", "uvicorn>=0.29", "orjson>=3.9"],
            "s3": ["boto3"],
            "changelog": ["git-cliff==2.5.0; python_version >= '3.8'"],
            # The experiment SDK needs nothing third-party; the extra exists so
            # `pip install vmn[exp]` resolves instead of warning about an unknown
            # extra and silently installing plain vmn.
            "exp": [],
            # GPU metrics need pynvml too, which stays out of every extra: it is
            # useless without a driver and would break installs on CPU-only hosts.
            "sysmetrics": ["psutil>=5.9"],
            # Autolog patches the framework the user already has, so vmn never
            # needs to install one.  These extras are for pinning, opt-in one at
            # a time — deliberately NOT folded into `exp`.
            "sklearn": ["scikit-learn"],
            "xgboost": ["xgboost"],
            "torch": ["torch", "lightning"],
            "keras": ["keras"],
            # Optional integrations — install the framework you already use, then
            # add the matching extra so vmn's helpers are available.
            "mlflow": ["mlflow-skinny"],
            "hf": ["transformers"],
            "optuna": ["optuna"],
            "ray": ["ray[tune]"],
        },
        package_dir={"version_stamp": "version_stamp"},
        packages=[
            "version_stamp",
            "version_stamp.compat",
            "version_stamp.core",
            "version_stamp.backends",
            "version_stamp.stamping",
            "version_stamp.cli",
            "version_stamp.devversion",
            "vmn_exp",
            "vmn_exp.sdk",
            "vmn_exp.cli",
            "vmn_exp.core",
            "vmn_exp.importers",
            "vmn_exp.integrations",
            "vmn_exp.registry",
            "vmn_exp.snapshot",
            "vmn_exp.storage",
            "vmn_exp.ui",
            "vmn_exp.ui.readers",
        ],
        package_data={
            "vmn_exp.ui": ["static/*", "static/assets/*"],
        },
        entry_points={
            "console_scripts": [
                "vmn = version_stamp.cli:main",
                "vmn-argcomplete-tcsh = "
                "version_stamp.cli.completion:tcsh_completion_main",
            ],
        },
        data_files=[("share/doc/vmn", ["README.md"])],
        license="MIT",
        include_package_data=True,
    )


def _setup_exp():
    """Slim vmn-exp distribution — built when ``VMN_DIST=exp``."""
    setuptools.setup(
        name="vmn-exp",
        version=version.version,
        author="Pavel Rogovoy",
        author_email="p.rogovoy@gmail.com",
        description="vmn experiment SDK — git-free recording and reading",
        long_description=long_description,
        long_description_content_type="text/markdown",
        python_requires=">=3.8",
        url="https://github.com/progovoy/vmn",
        install_requires=[
            "PyYAML>=5.4.1",
            "filelock>=3.2.0",
        ],
        extras_require={
            "s3": ["boto3"],
            "sysmetrics": ["psutil>=5.9"],
            "hf": ["transformers"],
            "optuna": ["optuna"],
            "ray": ["ray[tune]"],
        },
        packages=[
            "version_stamp",
            "version_stamp.core",
            "version_stamp.cli",
            "version_stamp.devversion",
            "vmn_exp",
            "vmn_exp.sdk",
            "vmn_exp.cli",
            "vmn_exp.core",
            "vmn_exp.storage",
            "vmn_exp.registry",
            "vmn_exp.snapshot",
            "vmn_exp.integrations",
        ],
        package_data={},
        license="MIT",
        include_package_data=False,
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

if os.environ.get("VMN_DIST") == "exp":
    _setup_exp()
else:
    _setup_default()
