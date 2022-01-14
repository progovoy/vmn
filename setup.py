import setuptools

from version_stamp import version

description = "Stamping utility"

with open("tests/requirements.txt") as fid:
    install_requires = fid.readlines()

setuptools.setup(
    name="vmn",
    version=version.version,
    author="Pavel Rogovoy",
    author_email="pavelr@final.israel",
    description=description,
    long_description=description,
    python_requires=">=3.6.0",
    url="https://github.com/final-israel/vmn",
    install_requires=install_requires,
    package_dir={"version_stamp": "version_stamp"},
    packages=["version_stamp"],
    entry_points={"console_scripts": ["vmn = version_stamp.vmn:main"]},
    include_package_data=True,
)
