"""The SDK's storage leaf modules are core's ``version_stamp.store`` ones
(plan 45 P5b): one implementation, every SDK name still importable."""
import pytest

from version_stamp.store import areas as core_areas
from version_stamp.store import per_process as core_per_process
from version_stamp.store import uri as core_uri
from vmn_exp.storage import areas, per_process, uri

AREAS_NAMES = [
    "RUNS", "SNAPSHOTS", "CODE", "SWEEPS", "REGISTRY", "REPORTS", "COMMENTS",
    "SETTINGS", "JOURNAL", "DEFAULT_ROOT", "local_store_root", "app_key",
    "app_name_of", "area_prefix",
]
URI_NAMES = ["StoreURI", "parse_store_uri", "s3_uri"]
PER_PROCESS_NAMES = ["PerProcess", "PerProcessLock"]


@pytest.mark.parametrize(
    "sdk, core, names",
    [
        (areas, core_areas, AREAS_NAMES),
        (uri, core_uri, URI_NAMES),
        (per_process, core_per_process, PER_PROCESS_NAMES),
    ],
)
def test_sdk_store_leaf_names_are_cores(sdk, core, names):
    for name in names:
        assert getattr(sdk, name) is getattr(core, name), name
