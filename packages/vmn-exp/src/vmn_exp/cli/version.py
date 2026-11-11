"""vmn-exp's own version, as ``vmn-exp --version`` and the server's ``/meta`` show it."""
from importlib import metadata


def installed_version():
    """The installed vmn-exp distribution's version; None when it is not installed."""
    try:
        return metadata.version("vmn-exp")
    except metadata.PackageNotFoundError:
        return None


def display_version(read_version):
    """What ``vmn-exp --version`` prints: *read_version*'s string, or ``unknown``."""
    return read_version() or "unknown"
