import setuptools

from version_stamp import __version__

description = 'Stamping utility'

install_requires=['python-hglib>=2.6', 'lockfile', 'GitPython>=2.1.11']

setuptools.setup(
    name='version_stamp',
    version=__version__,
    author="Pavel Rogovoy",
    author_email='pavelr@final.israel',
    description=description,
    long_description=description,
    python_requires='>=3.5.0',
    url="https://github.com/final-israel/ver_stamp",
    install_requires=install_requires,
    package_dir={'version_stamp': 'version_stamp'},
    packages=['version_stamp',],
    entry_points={
        'console_scripts': ['ver-stamp = version_stamp.ver_stamp:main',
                            'ver_stamp = version_stamp.ver_stamp:main',
                            'version_manager = version_stamp.ver_stamp:main',
                            'get-version = version_stamp.get_version:main',
                            'get_version = version_stamp.get_version:main',
                            'goto-version = version_stamp.goto_version:main',
                            'goto_version = version_stamp.goto_version:main']
    },
)
