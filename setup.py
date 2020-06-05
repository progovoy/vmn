import setuptools

from version_stamp import __version__

description = 'Stamping utility'

install_requires=[
    'python-hglib>=2.6.1',
    'lockfile>=0.12.2',
    'GitPython>=3.1.3',
    'PyYAML>=5.3.1',
]

setuptools.setup(
    name='vmn',
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
        'console_scripts': ['vmn = version_stamp.vmn:main']
    },
)
