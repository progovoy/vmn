# Not be confused. This is the version of the ver_stamp utility
from version_stamp import version as our_version

__version__ = our_version.version

# Install the alias finder so old import paths keep working after module moves.
from version_stamp import _aliases as _aliases_mod
_aliases_mod.install()
