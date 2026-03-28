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
    package_dir={"version_stamp": "version_stamp"},
    packages=["version_stamp"],
    entry_points={"console_scripts": ["vmn = version_stamp.vmn:main"]},
    license="MIT",
    include_package_data=True,
)
