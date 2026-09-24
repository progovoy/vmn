import setuptools

from version_stamp import version

description = "Stamping utility"

with open("README.md") as fid:
    long_description = fid.read()

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
        # The experiment SDK needs nothing third-party; the extra exists so the
        # documented `pip install vmn[exp]` resolves instead of warning about an
        # unknown extra and silently installing plain vmn.
        "exp": [],
        # GPU metrics need pynvml too, which stays out of every extra: it is
        # useless without a driver and would break installs on CPU-only hosts.
        "sysmetrics": ["psutil>=5.9"],
        # Autolog patches the framework the user already has, so vmn never needs
        # to install one. These extras are for pinning, opt-in one at a time —
        # deliberately NOT folded into `exp`, which would turn logging three
        # numbers into a multi-gigabyte download.
        "sklearn": ["scikit-learn"],
        "xgboost": ["xgboost"],
        "torch": ["torch", "lightning"],
        "keras": ["keras"],
    },
    package_dir={"version_stamp": "version_stamp"},
    packages=[
        "version_stamp",
        "version_stamp.compat",
        "version_stamp.core",
        "version_stamp.backends",
        "version_stamp.stamping",
        "version_stamp.cli",
        "version_stamp.exp",
        "version_stamp.ui",
        "version_stamp.ui.readers",
    ],
    package_data={
        "version_stamp.ui": ["static/*", "static/assets/*"],
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
