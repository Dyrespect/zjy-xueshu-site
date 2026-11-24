"""语义向量：读 .npy、远程编码器（成功 / 超时 / 连着失败就暂停）、引擎带向量找和失败退回关键词。

不连真的小服务：用 httpx.MockTransport 假装它。
"""

import json
import struct
from pathlib import Path

import httpx
import pytest

from app.figures.engine import FigureEngine
from app.figures.vectors import EmbedError, RemoteEmbedder, load_npy
from tests.figures.conftest import needs_engine


def _write_npy(path: Path, rows: list[list[float]], descr: str = "<f2") -> None:
    fmt = {"<f2": "e", "<f4": "f"}[descr]
    header = repr({"descr": descr, "fortran_order": False, "shape": (len(rows), len(rows[0]))}).encode()
    header += b" " * (64 - (10 + len(header) + 1) % 64) + b"\n"
    with open(path, "wb") as f:
        f.write(b"\x93NUMPY\x01\x00" + struct.pack("<H", len(header)) + header)
        for r in rows:
            f.write(struct.pack(f"<{len(r)}{fmt}", *r))


@pytest.mark.parametrize("descr", ["<f2", "<f4"])
def test_load_npy_and_matmul(tmp_path, descr):
    p = tmp_path / "v.npy"
    _write_npy(p, [[1.0, 0.0, 0.5], [0.0, 1.0, 0.25]], descr)
    m = load_npy(p)
    assert len(m) == 2
    assert m @ [1.0, 2.0, 4.0] == pytest.approx([3.0, 3.0])


def _embedder(handler, **kw) -> RemoteEmbedder:
    return RemoteEmbedder("http://mini:8766", "Instruct: x\nQuery:", transport=httpx.MockTransport(handler), **kw)


def test_embedder_batches_and_caches():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        calls.append(body["texts"])
        assert body["instruct"] == "Instruct: x\nQuery:"
        return httpx.Response(200, json={"vectors": [[float(len(t)), 1.0] for t in body["texts"]]})

    e = _embedder(handler)
    got = e.embed_many(["甲", "乙乙", "甲"])
    assert list(got["乙乙"]) == [2.0, 1.0]
    assert calls == [["甲", "乙乙"]]  # 一个请求、去重
    e.embed_many(["甲"])
    assert calls == [["甲", "乙乙"]]  # 第二次走缓存
    assert e.encode(["乙乙"])[0].astype("float32") is e.cached("乙乙")


def test_embedder_failure_pauses_after_two():
    n = {"calls": 0}

    def handler(req):
        n["calls"] += 1
        raise httpx.ReadTimeout("timed out", request=req)

    e = _embedder(handler)
    assert e.embed_many(["a"]) == {"a": None}
    with pytest.raises(EmbedError):
        e.embed_one("b")
    assert e.paused
    assert e.embed_many(["c"]) == {"c": None}
    assert n["calls"] == 2  # 暂停期间不再请求


@needs_engine
def test_engine_uses_vectors_and_falls_back(engine):
    """同一个引擎：小服务正常时带向量找；小服务挂了这次退回关键词，下次还能用向量（状态复原）。"""
    state = {"down": False}
    V = engine.vectors
    assert V is not None

    def handler(req):
        if state["down"]:
            raise httpx.ConnectError("refused", request=req)
        texts = json.loads(req.content)["texts"]
        return httpx.Response(200, json={"vectors": [list(V.row(7)) for _ in texts]})

    emb = _embedder(handler)
    emb.FAILS_TO_PAUSE = 99
    eng = FigureEngine(engine.E, engine.docs, V, emb)
    try:
        res = eng.full_search("被试内实验的试次流程")
        assert res.used_vectors is True
        assert eng.E._VEC["状态"] == "能用"
        assert not any(isinstance(k, tuple) for k in eng.E._VEC)  # 这次的查询向量用完拿掉

        state["down"] = True
        emb._cache.clear()
        res = eng.full_search("有调节的中介模型 问卷")
        assert res.used_vectors is False and len(res.main.same) == 16
        assert eng.E._VEC["状态"] == "能用"  # 一次失败不把进程卡成只用关键词

        state["down"] = False
        assert eng.full_search("有调节的中介模型 问卷").used_vectors is True
    finally:
        # 把共享的引擎模块还原成只用关键词（别的测试用同一个模块）
        engine.E._VEC.update(V=None, M=None, 状态=f"没用上语义检索：{engine.vector_note}")
        for k in [k for k in engine.E._VEC if isinstance(k, tuple)]:
            del engine.E._VEC[k]
