"""store.yml at a store root (docs/plans/14-store-layout.md §2.3), on
in-memory fakes and a hand-advanced clock. Cases copied from the SDK's
packages/vmn-exp/tests/test_store_marker*.py."""
import os

import pytest
import yaml

from version_stamp.store import marker
from version_stamp.store.marker import MissingStoreError, StoreLayoutError

BUCKET, PREFIX = "bucket", "team/vmn"
NOW = 1767225600.0  # 2026-01-01T00:00:00Z


class FakeClock:
    def __init__(self, now=NOW):
        self.now = now
        self.sleeps = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class FakeS3Error(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _Body:
    def __init__(self, data):
        self._data = data

    def read(self):
        return self._data


class FakeS3Client:
    def __init__(self):
        self.objects = {}
        self.puts = 0

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise FakeS3Error("NoSuchKey")
        return {"Body": _Body(self.objects[(Bucket, Key)])}

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None):
        if IfNoneMatch == "*" and (Bucket, Key) in self.objects:
            raise FakeS3Error("PreconditionFailed")
        self.puts += 1
        self.objects[(Bucket, Key)] = Body

    def list_objects_v2(self, Bucket, Prefix, Delimiter=None, MaxKeys=1000):
        keys = sorted(k for b, k in self.objects if b == Bucket and k.startswith(Prefix))
        contents, prefixes = [], set()
        for key in keys:
            rest = key[len(Prefix):]
            if Delimiter and Delimiter in rest:
                prefixes.add(Prefix + rest.split(Delimiter)[0] + Delimiter)
            else:
                contents.append({"Key": key})
        page = {"Contents": contents[:MaxKeys]} if contents else {}
        if prefixes:
            page["CommonPrefixes"] = [{"Prefix": p} for p in sorted(prefixes)]
        return page


class FakeS3Storage:
    def __init__(self, client, prefix=PREFIX, area="runs"):
        self._s3 = client
        self.bucket = BUCKET
        self.prefix = f"{prefix}/{area}"


class FakeLocalStorage:
    def __init__(self, root, area="runs"):
        self.root, self.area = root, area


@pytest.fixture(autouse=True)
def _fresh_cache():
    marker.forget_checked()
    yield
    marker.forget_checked()


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def s3():
    return FakeS3Client()


def _put(s3, name, body=b"x"):
    s3.objects[(BUCKET, f"{PREFIX}/{name}")] = body


def _marker_of(s3):
    return yaml.safe_load(s3.objects[(BUCKET, f"{PREFIX}/store.yml")])


def _check(storage, writer, clock):
    marker.check_store(storage, writer, clock, clock, clock.sleep)


def test_new_marker_is_deterministic_given_now():
    assert marker.new_marker(NOW) == {
        "layout": 2,
        "created_at": "2026-01-01T00:00:00Z",
        "journal": {"partition": "minute"},
    }
    assert marker.new_marker(NOW) == marker.new_marker(NOW)


def test_writer_creates_the_marker_once(s3, clock):
    _check(FakeS3Storage(s3), True, clock)
    assert _marker_of(s3) == marker.new_marker(NOW)
    clock.now += 3600
    marker.forget_checked()
    _check(FakeS3Storage(s3), True, clock)
    assert s3.puts == 1
    assert _marker_of(s3)["created_at"] == "2026-01-01T00:00:00Z"


def test_a_checked_root_is_not_read_again(s3, clock):
    _check(FakeS3Storage(s3), True, clock)
    s3.objects.clear()
    _check(FakeS3Storage(s3), True, clock)
    assert s3.puts == 1


def test_reader_does_not_create_the_marker(s3, clock):
    _check(FakeS3Storage(s3), False, clock)
    assert s3.objects == {}


def test_a_lost_create_race_keeps_the_winners_marker(s3, clock):
    where = marker.root_of(FakeS3Storage(s3))
    where.create("layout: 2\ncreated_at: first\n", clock, clock.sleep)
    where.create("layout: 2\ncreated_at: second\n", clock, clock.sleep)
    assert _marker_of(s3)["created_at"] == "first"


@pytest.mark.parametrize("writer", [True, False])
def test_unknown_layout_refused(s3, clock, writer):
    _put(s3, "store.yml", b"layout: 7\n")
    with pytest.raises(StoreLayoutError, match="layout 7"):
        _check(FakeS3Storage(s3), writer, clock)


@pytest.mark.parametrize("writer", [True, False])
def test_v1_records_refused_with_migrate_hint(s3, clock, writer):
    _put(s3, "my_app/v1/metadata.yml")
    with pytest.raises(StoreLayoutError, match="run `vmn-exp migrate`"):
        _check(FakeS3Storage(s3), writer, clock)
    assert (BUCKET, f"{PREFIX}/store.yml") not in s3.objects


@pytest.mark.parametrize("prefix", ["vmn-experiments", "vmn-snapshots"])
def test_default_object_prefixes_refused(s3, clock, prefix):
    s3.objects[(BUCKET, f"{prefix}/my-app/r1/metadata.yml")] = b"x"
    with pytest.raises(StoreLayoutError, match="vmn-exp migrate"):
        _check(FakeS3Storage(s3, prefix="vmn"), True, clock)


def test_v2_areas_without_marker_are_adopted(s3, clock):
    _put(s3, "snapshots/app/v1/metadata.yml")
    _check(FakeS3Storage(s3), True, clock)
    assert _marker_of(s3)["layout"] == 2


def test_migrating_refuses_writers_not_readers(s3, clock):
    _put(s3, "store.yml", b"layout: 2\nmigrating: true\n")
    with pytest.raises(StoreLayoutError, match="migrat"):
        _check(FakeS3Storage(s3), True, clock)
    _check(FakeS3Storage(s3), False, clock)


def test_reader_of_an_empty_root_gets_missing_store(s3, clock):
    uri = f"s3://{BUCKET}/{PREFIX}"
    with pytest.raises(MissingStoreError) as exc:
        marker.require_store(FakeS3Storage(s3), uri)
    assert str(exc.value) == f"no vmn store at {uri}"
    _check(FakeS3Storage(s3), True, clock)
    marker.require_store(FakeS3Storage(s3), uri)


def test_require_store_checks_the_authoritative_remote(s3):
    _put(s3, "store.yml", b"layout: 7\n")

    class Cached:
        _remote = FakeS3Storage(s3)

    with pytest.raises(StoreLayoutError, match="layout 7"):
        marker.require_store(Cached())


def test_unknown_backends_are_not_checked(clock):
    _check(object(), True, clock)
    assert marker.root_of(object()) is None


def test_local_writer_creates_a_readable_marker(tmp_path, clock):
    root = str(tmp_path / "store")
    _check(FakeLocalStorage(root), True, clock)
    with open(os.path.join(root, "store.yml")) as f:
        assert yaml.safe_load(f) == marker.new_marker(NOW)
    assert os.stat(os.path.join(root, "store.yml")).st_mode & 0o044 == 0o044
    assert os.listdir(root) == ["store.yml"]


def test_local_v1_records_in_the_dot_vmn_beside_the_root_refused(tmp_path, clock):
    rec = tmp_path / ".vmn" / "my" / "app" / "snapshots" / "s1"
    rec.mkdir(parents=True)
    (rec / "metadata.yml").write_text("verstr: x\n")
    with pytest.raises(StoreLayoutError, match="vmn-exp migrate"):
        _check(FakeLocalStorage(str(tmp_path / ".vmn" / "store")), True, clock)


@pytest.mark.parametrize("key", ["stamping", "vmn_info"])
def test_a_stamp_snapshot_beside_the_root_is_no_v1_record(tmp_path, clock, key):
    rec = tmp_path / ".vmn" / "my_app" / "snapshots" / "0.0.1"
    rec.mkdir(parents=True)
    (rec / "metadata.yml").write_text(yaml.safe_dump({key: {"version": "0.0.1"}}))
    root = str(tmp_path / ".vmn" / "store")
    _check(FakeLocalStorage(root), True, clock)
    assert os.path.exists(os.path.join(root, "store.yml"))


@pytest.mark.parametrize("text", ["key: [unclosed\n", "- a list\n", "just text\n"])
def test_a_v1_record_that_is_no_stamp_dict_is_still_v1(tmp_path, clock, text):
    rec = tmp_path / ".vmn" / "my_app" / "snapshots" / "s1"
    rec.mkdir(parents=True)
    (rec / "metadata.yml").write_text(text)
    with pytest.raises(StoreLayoutError, match="vmn-exp migrate"):
        _check(FakeLocalStorage(str(tmp_path / ".vmn" / "store")), True, clock)


def test_publish_locked_waits_via_the_injected_sleep(tmp_path, clock):
    path = str(tmp_path / "store.yml")
    os.mkdir(str(tmp_path / ".store.yml.lock"))  # another creator holds it
    with pytest.raises(StoreLayoutError, match="stale"):
        marker._publish_locked(path, str(tmp_path / "tmp"), clock, clock.sleep)
    assert clock.now - NOW >= 30.0
    assert clock.sleeps and set(clock.sleeps) == {0.01}
    assert not os.path.exists(path)


def test_publish_locked_names_a_stale_lock_it_waited_out(tmp_path, clock):
    path, lock = str(tmp_path / "store.yml"), str(tmp_path / ".store.yml.lock")
    os.mkdir(lock)  # a creator that died holding it
    with pytest.raises(StoreLayoutError) as exc:
        marker._publish_locked(path, str(tmp_path / "tmp"), clock, clock.sleep)
    assert str(exc.value) == (
        f"{tmp_path} has no store.yml after waiting 30s on {lock}: if no vmn "
        "writer is running, it is stale from a crashed one: remove it and retry")


def test_publish_locked_returns_once_the_winner_publishes(tmp_path, clock):
    path = str(tmp_path / "store.yml")
    os.mkdir(str(tmp_path / ".store.yml.lock"))

    def sleep(seconds):
        clock.sleep(seconds)
        if len(clock.sleeps) == 3:
            with open(path, "w") as f:
                f.write("layout: 2\n")

    marker._publish_locked(path, str(tmp_path / "tmp"), clock, sleep)
    assert len(clock.sleeps) == 3


def test_publish_locked_publishes_when_it_wins_the_lock(tmp_path, clock):
    path, tmp = str(tmp_path / "store.yml"), str(tmp_path / "tmp")
    with open(tmp, "w") as f:
        f.write("layout: 2\n")
    marker._publish_locked(path, tmp, clock, clock.sleep)
    assert os.listdir(str(tmp_path)) == ["store.yml"]
    assert clock.sleeps == []


def test_the_module_lock_is_per_process():
    from version_stamp.store.per_process import PerProcessLock

    assert isinstance(marker._lock, PerProcessLock)


class FakeTime:
    """A wall clock that can jump and a monotonic one only ``sleep`` advances."""

    def __init__(self, wall_jump):
        self.wall, self.mono = NOW, 0.0
        self.sleeps = []
        self._wall_jump = wall_jump

    def now(self):
        return self.wall

    def monotonic(self):
        return self.mono

    def sleep(self, seconds):
        if not self.sleeps:
            self.wall += self._wall_jump
        self.sleeps.append(seconds)
        self.mono += seconds
        self.wall += seconds


@pytest.mark.parametrize("wall_jump", [3600.0, -3600.0])
def test_publish_locked_waits_on_monotonic_time_across_wall_clock_jumps(tmp_path, wall_jump):
    time = FakeTime(wall_jump)
    os.mkdir(str(tmp_path / ".store.yml.lock"))
    with pytest.raises(StoreLayoutError):
        marker._publish_locked(str(tmp_path / "store.yml"), str(tmp_path / "tmp"),
                               monotonic=time.monotonic, sleep=time.sleep, wait_sec=30.0)
    assert sum(time.sleeps) == pytest.approx(30.0, abs=0.011)


def test_check_store_stamps_created_at_from_now_not_monotonic(s3):
    time = FakeTime(0.0)
    marker.check_store(FakeS3Storage(s3), True, now=time.now,
                       monotonic=time.monotonic, sleep=time.sleep)
    assert _marker_of(s3)["created_at"] == "2026-01-01T00:00:00Z"


V1_HINT = ("is a v1 store written by an older vmn-exp (records but no store.yml): "
           "run `vmn-exp migrate` (pip install vmn-exp)")
NOT_A_STORE = "is not a vmn store (no store.yml, and its contents are not vmn records)"


@pytest.mark.parametrize("writer", [True, False])
def test_unknown_layout_names_vmn_not_vmn_exp(s3, clock, writer):
    _put(s3, "store.yml", b"layout: 7\n")
    with pytest.raises(StoreLayoutError) as exc:
        _check(FakeS3Storage(s3), writer, clock)
    assert str(exc.value) == (f"{BUCKET}/{PREFIX} has store layout 7; "
                              "this vmn knows layout 2 only: upgrade vmn")


@pytest.mark.parametrize("writer", [True, False])
def test_v1_hint_reads_for_a_vmn_only_user(s3, clock, writer):
    _put(s3, "my_app/v1/metadata.yml")
    with pytest.raises(StoreLayoutError) as exc:
        _check(FakeS3Storage(s3), writer, clock)
    assert str(exc.value) == f"{BUCKET}/{PREFIX} {V1_HINT}"


@pytest.mark.parametrize("writer", [True, False])
@pytest.mark.parametrize("names", [
    ["photos/cat.jpg"],
    ["README.md", "photos/cat.jpg"],
    ["my_app/v1/notes.txt"],
    ["my_app/metadata.yml"],
])
def test_unrelated_prefix_is_not_a_vmn_store(s3, clock, writer, names):
    for name in names:
        _put(s3, name)
    with pytest.raises(StoreLayoutError) as exc:
        _check(FakeS3Storage(s3), writer, clock)
    assert str(exc.value) == f"{BUCKET}/{PREFIX} {NOT_A_STORE}"
    assert (BUCKET, f"{PREFIX}/store.yml") not in s3.objects


def test_reader_of_an_unrelated_prefix_is_told_it_is_not_a_store(s3):
    _put(s3, "photos/cat.jpg")
    with pytest.raises(StoreLayoutError, match="is not a vmn store"):
        marker.require_store(FakeS3Storage(s3), f"s3://{BUCKET}/{PREFIX}")


def test_v1_records_are_found_past_unrelated_dirs(s3, clock):
    _put(s3, "aaa/notes.txt")
    _put(s3, "my_app/v1/metadata.yml")
    with pytest.raises(StoreLayoutError, match="v1 store"):
        _check(FakeS3Storage(s3), True, clock)


def test_default_prefix_content_that_is_not_records_is_not_v1(s3, clock):
    s3.objects[(BUCKET, "vmn-experiments/notes.txt")] = b"x"
    _check(FakeS3Storage(s3, prefix="vmn"), True, clock)
    assert (BUCKET, "vmn/store.yml") in s3.objects


@pytest.mark.parametrize("writer", [True, False])
def test_unrelated_local_directory_is_not_a_vmn_store(tmp_path, clock, writer):
    (tmp_path / "some_dir").mkdir()
    (tmp_path / "notes.txt").write_text("x")
    with pytest.raises(StoreLayoutError) as exc:
        _check(FakeLocalStorage(str(tmp_path)), writer, clock)
    assert str(exc.value) == f"{tmp_path} {NOT_A_STORE}"
    assert not (tmp_path / "store.yml").exists()


def test_local_root_level_v1_records_get_the_v1_hint(tmp_path, clock):
    rec = tmp_path / "my_app" / "v1"
    rec.mkdir(parents=True)
    (rec / "metadata.yml").write_text("verstr: v1\n")
    with pytest.raises(StoreLayoutError, match="v1 store"):
        _check(FakeLocalStorage(str(tmp_path)), True, clock)


def test_stray_files_beside_a_store_do_not_make_it_foreign(s3, tmp_path, clock):
    _put(s3, "vmn_metadata.yml")
    _check(FakeS3Storage(s3), True, clock)
    assert (BUCKET, f"{PREFIX}/store.yml") in s3.objects
    (tmp_path / "vmn_metadata.yml").write_text("verstr: x\n")
    _check(FakeLocalStorage(str(tmp_path)), True, clock)
    assert (tmp_path / "store.yml").exists()


RECORD_NAMES = ["0.0.1.dev.abc", "1.2.0-dev.a1b2c3d.e4f5a6b", "1.2.0-dev.a1b2c3d.e4f5g6h",
                "1.2.0.3", "2.0.0-rc.1", "1.0.0_plus_build.7"]


@pytest.mark.parametrize("writer", [True, False])
@pytest.mark.parametrize("verstr", RECORD_NAMES)
def test_a_local_record_dir_with_no_files_is_v1(tmp_path, clock, writer, verstr):
    (tmp_path / "my_app" / verstr).mkdir(parents=True)
    with pytest.raises(StoreLayoutError) as exc:
        _check(FakeLocalStorage(str(tmp_path)), writer, clock)
    assert str(exc.value) == f"{tmp_path} {V1_HINT}"


@pytest.mark.parametrize("writer", [True, False])
@pytest.mark.parametrize("verstr", RECORD_NAMES)
def test_an_s3_record_without_metadata_is_v1(s3, clock, writer, verstr):
    _put(s3, f"my_app/{verstr}/.claim")
    with pytest.raises(StoreLayoutError) as exc:
        _check(FakeS3Storage(s3), writer, clock)
    assert str(exc.value) == f"{BUCKET}/{PREFIX} {V1_HINT}"


TMP_LIKE = ["foo/bar", "photos/2024", "my_app/notes", "builds/1.2", "builds/1.2.3abc"]


@pytest.mark.parametrize("writer", [True, False])
@pytest.mark.parametrize("sub", TMP_LIKE)
def test_tmp_like_local_dirs_are_not_a_vmn_store(tmp_path, clock, writer, sub):
    (tmp_path / sub).mkdir(parents=True)
    with pytest.raises(StoreLayoutError) as exc:
        _check(FakeLocalStorage(str(tmp_path)), writer, clock)
    assert str(exc.value) == f"{tmp_path} {NOT_A_STORE}"
    assert not (tmp_path / "store.yml").exists()


@pytest.mark.parametrize("writer", [True, False])
@pytest.mark.parametrize("sub", TMP_LIKE)
def test_tmp_like_s3_prefixes_are_not_a_vmn_store(s3, clock, writer, sub):
    _put(s3, f"{sub}/file.txt")
    with pytest.raises(StoreLayoutError) as exc:
        _check(FakeS3Storage(s3), writer, clock)
    assert str(exc.value) == f"{BUCKET}/{PREFIX} {NOT_A_STORE}"
    assert (BUCKET, f"{PREFIX}/store.yml") not in s3.objects


def test_writer_marks_an_existing_empty_directory(tmp_path, clock):
    (tmp_path / ".gitignore").write_text("*\n")
    _check(FakeLocalStorage(str(tmp_path)), True, clock)
    assert (tmp_path / "store.yml").exists()
