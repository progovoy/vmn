"""The conf files vmn loads for a branch, for the experiment SDK (which
reaches vmn only through ``version_stamp.store``): it reads the conf the
writer reads, so both name the same store (plan 45)."""
from version_stamp.core.utils import branch_conf_candidates

__all__ = ["branch_conf_candidates"]
