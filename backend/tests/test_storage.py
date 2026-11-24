import io

import pytest

from app.core.storage import LocalStorage, StorageError, build_storage


@pytest.fixture
def storage(tmp_path):
    return LocalStorage(tmp_path / "files")


def test_save_read_delete_bytes(storage):
    rel = storage.save("你好".encode(), folder="uploads/2026-11", filename="论文.pdf")
    assert rel.startswith("uploads/2026-11/") and rel.endswith("_论文.pdf")
    assert not rel.startswith("/")
    assert storage.exists(rel)
    assert storage.read_bytes(rel) == "你好".encode()
    with storage.open(rel) as f:
        assert f.read() == "你好".encode()
    assert storage.delete(rel) is True
    assert storage.exists(rel) is False
    assert storage.delete(rel) is False


def test_save_stream(storage):
    rel = storage.save(io.BytesIO(b"x" * 3_000_000), folder="big", filename="a.bin")
    assert len(storage.read_bytes(rel)) == 3_000_000


def test_same_name_never_overwrites(storage):
    a = storage.save(b"1", folder="f", filename="same.txt")
    b = storage.save(b"2", folder="f", filename="same.txt")
    assert a != b
    assert storage.read_bytes(a) == b"1" and storage.read_bytes(b) == b"2"


def test_filename_is_sanitized(storage):
    rel = storage.save(b"1", folder="f", filename="../../etc/pass wd?.txt")
    assert ".." not in rel and "/etc/" not in rel
    assert storage.local_path(rel).parent == (storage.root / "f")


@pytest.mark.parametrize("bad", ["../x", "/etc/passwd", "a/../../x", "a\\b"])
def test_path_traversal_rejected(storage, bad):
    with pytest.raises(StorageError):
        storage.local_path(bad)


def test_folder_with_dotdot_rejected(storage):
    with pytest.raises(StorageError):
        storage.save(b"1", folder="../outside", filename="a.txt")


def test_missing_file(storage):
    with pytest.raises(FileNotFoundError):
        storage.read_bytes("nope/none.txt")


def test_build_storage_lives_under_data_dir(settings):
    s = build_storage(settings)
    assert isinstance(s, LocalStorage)
    assert s.root == (settings.DATA_DIR / "files").resolve()
