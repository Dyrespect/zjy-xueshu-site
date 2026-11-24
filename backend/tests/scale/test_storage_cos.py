"""对象存储（设计第六节）：CosStorage 走官方 SDK，对着本机起的假 COS 服务测（不联网、不读真密钥）。

假服务只认最基本的 PUT / GET / HEAD / DELETE，并且要求每个请求都带 COS 签名（q-sign-algorithm=sha1…），
签名链接要带 q-signature 参数。本地和对象存储同一套接口：同一组断言两边都跑。
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import pytest

from app.core.config import Settings
from app.core.storage import CosStorage, LocalStorage, Storage, StorageError, build_storage

FAKE_ID = "AKIDfake-not-a-real-id"  # 不是真密钥：真 SecretId 是 AKID + 32 位，这里故意不像


class _FakeCos(BaseHTTPRequestHandler):
    objects: dict[str, bytes] = {}
    auth_seen: list[str] = []

    def log_message(self, *args):  # 安静
        pass

    def _key(self) -> str:
        return unquote(urlsplit(self.path).path.lstrip("/"))

    def _authorized(self) -> bool:
        auth = self.headers.get("Authorization", "")
        q = parse_qs(urlsplit(self.path).query)
        ok = (auth.startswith("q-sign-algorithm=sha1") and f"q-ak={FAKE_ID}" in auth) or "q-signature" in q
        self.auth_seen.append(auth or "presigned")
        if not ok:
            self._send(403, b"<Error><Code>AccessDenied</Code></Error>")
        return ok

    def _send(self, code: int, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def do_PUT(self):
        if not self._authorized():
            return
        n = int(self.headers.get("Content-Length") or 0)
        self.objects[self._key()] = self.rfile.read(n)
        self._send(200, headers={"ETag": '"x"'})

    def do_GET(self):
        if not self._authorized():
            return
        data = self.objects.get(self._key())
        if data is None:
            self._send(404, b"<Error><Code>NoSuchKey</Code><Message>no</Message></Error>", {"Content-Type": "application/xml"})
        else:
            self._send(200, data, {"Content-Type": "application/octet-stream"})

    def do_HEAD(self):
        if not self._authorized():
            return
        self._send(200 if self._key() in self.objects else 404)

    def do_DELETE(self):
        if not self._authorized():
            return
        self.objects.pop(self._key(), None)
        self._send(204)


@pytest.fixture
def fake_cos(monkeypatch):
    for k in ("NO_PROXY", "no_proxy"):  # 本机有代理：连 127.0.0.1 不走代理
        monkeypatch.setenv(k, "127.0.0.1,localhost")
    _FakeCos.objects, _FakeCos.auth_seen = {}, []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _FakeCos)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def _cos(endpoint: str) -> CosStorage:
    return CosStorage(bucket="xueshu-test-1250000000", region="ap-shanghai", secret_id=FAKE_ID,
                      secret_key="fake-secret-key-not-real", prefix="psyppt/", endpoint=endpoint, timeout=5)


def _same_contract(st: Storage) -> None:
    rel = st.save("论文正文".encode(), folder="intake/7", filename="../../论文 v2.pdf")
    assert rel.startswith("intake/7/") and rel.endswith("_论文_v2.pdf")
    assert st.exists(rel) and st.read_bytes(rel) == "论文正文".encode()
    with st.open(rel) as f:
        assert f.read() == "论文正文".encode()
    other = st.save(b"x", folder="intake/7", filename="论文 v2.pdf")
    assert other != rel  # 同名不覆盖
    with pytest.raises(FileNotFoundError):
        st.read_bytes("intake/7/nope.pdf")
    with pytest.raises(StorageError):
        st.read_bytes("../app.db")
    assert st.delete(rel) is True and st.delete(rel) is False and not st.exists(rel)


def test_local_storage_contract(tmp_path):
    st = LocalStorage(tmp_path / "files")
    _same_contract(st)
    assert st.signed_url("a/b.pdf") is None  # 本地没有签名链接：走应用下载（先校验归属）


def test_cos_storage_contract_with_fake_server(fake_cos):
    st = _cos(fake_cos)
    _same_contract(st)
    assert all(k.startswith("psyppt/") for k in _FakeCos.objects)  # 只在自己的前缀下
    assert _FakeCos.auth_seen and all(a.startswith("q-sign-algorithm=sha1") for a in _FakeCos.auth_seen)


def test_cos_streams_file_objects_and_signed_url(fake_cos, tmp_path):
    st = _cos(fake_cos)
    big = tmp_path / "交接包.zip"
    big.write_bytes(b"z" * (3 * 1024 * 1024))
    with open(big, "rb") as f:
        rel = st.save(f, folder="handoffs/3", filename="交接包.zip")
    assert st.read_bytes(rel) == big.read_bytes()
    url = st.signed_url(rel, expires=120, filename="成品.pptx")
    assert url and "q-signature" in url and "psyppt/handoffs/3/" in unquote(url)
    r = httpx.get(url, timeout=5, trust_env=False)
    assert r.status_code == 200 and r.content == big.read_bytes()


def test_storage_backend_switch_is_config_only(tmp_path, fake_cos):
    base = dict(_env_file=None, DATA_DIR=tmp_path / "data", DATABASE_URL="sqlite://")
    assert isinstance(build_storage(Settings(**base)), LocalStorage)
    s = Settings(**base, STORAGE_BACKEND="cos", COS_BUCKET="xueshu-test-1250000000", COS_REGION="ap-shanghai",
                 COS_SECRET_ID=FAKE_ID, COS_SECRET_KEY="fake-secret-key-not-real", COS_ENDPOINT=fake_cos)
    st = build_storage(s)
    assert isinstance(st, CosStorage) and st.read_bytes(st.save(b"ok", folder="x", filename="a.txt")) == b"ok"
    with pytest.raises(ValueError, match="COS_BUCKET"):
        Settings(**base, STORAGE_BACKEND="cos")
