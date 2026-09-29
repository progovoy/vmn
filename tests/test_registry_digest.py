"""Local file / directory digests for reference datasets (plan 06)."""
import hashlib
import os

from vmn_exp.registry.digest import local_digest


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def test_file_digest_is_sha256(tmp_path):
    path = str(tmp_path / "data.csv")
    _write(path, b"a,b\n1,2\n")
    info = local_digest(path)
    assert info["digest"] == "sha256:" + hashlib.sha256(b"a,b\n1,2\n").hexdigest()


def test_dir_manifest_digest_is_order_independent_and_content_sensitive(tmp_path):
    one, two = str(tmp_path / "one"), str(tmp_path / "two")
    _write(os.path.join(one, "b.txt"), b"B")
    _write(os.path.join(one, "sub", "a.txt"), b"A")
    _write(os.path.join(two, "sub", "a.txt"), b"A")
    _write(os.path.join(two, "b.txt"), b"B")
    digest = local_digest(one)["digest"]
    assert digest == local_digest(two)["digest"]

    manifest = "".join(
        f"{rel}\0{hashlib.sha256(data).hexdigest()}\n"
        for rel, data in (("b.txt", b"B"), ("sub/a.txt", b"A"))
    )
    assert digest == "sha256:" + hashlib.sha256(manifest.encode()).hexdigest()

    _write(os.path.join(two, "b.txt"), b"changed")
    assert local_digest(two)["digest"] != digest
    os.rename(os.path.join(one, "b.txt"), os.path.join(one, "c.txt"))
    assert local_digest(one)["digest"] != digest


def test_size_and_file_count(tmp_path):
    root = str(tmp_path / "ds")
    _write(os.path.join(root, "x.bin"), b"12345")
    _write(os.path.join(root, "d", "y.bin"), b"123")
    assert local_digest(root)["size"] == 8
    assert local_digest(root)["files"] == 2
    single = local_digest(os.path.join(root, "x.bin"))
    assert (single["size"], single["files"]) == (5, 1)
