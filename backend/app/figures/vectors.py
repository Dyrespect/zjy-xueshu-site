"""语义向量的两半：图库向量（本机读 .npy）和查询向量（远程小服务算）。

- 图库向量 `图库向量.npy`（7349×1024，float16）用 numpy 读成 float32，`VectorMatrix @ q` 返回每张图和 q
  的点积（numpy 数组）——找图引擎的 `_fuse` 直接能用。11-15 主窗口把纯 Python 点积换成 numpy（一次搜索省 0.3–0.6 秒）。
- 查询向量由 mini 上的小服务算（Qwen3-Embedding-0.6B，跟图库向量同一个模型）：POST EMBED_URL/embed
  `{"texts": [...], "instruct": ...}` → `{"vectors": [[...]]}`，已归一化。不走代理（trust_env=False）。
  `RemoteEmbedder.encode` 的签名照 sentence-transformers，引擎的 `_qvec` 把它当模型用。
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from collections.abc import Iterable, Sequence
from pathlib import Path

import httpx
import numpy as np

log = logging.getLogger("app.figures.vectors")


class QueryVector(np.ndarray):
    """一条查询向量（float32）。引擎会调 `.astype("float32")`，这里原样返回自己（缓存命中时还是同一个对象）。"""

    def astype(self, *_a, **_k) -> "QueryVector":  # type: ignore[override]
        return self


def _qv(values: Sequence[float]) -> QueryVector:
    return np.asarray(values, dtype=np.float32).view(QueryVector)


class VectorMatrix:
    """图库向量，只读。第 i 行对应引擎 docs 的第 i 张图。"""

    def __init__(self, m: np.ndarray) -> None:
        self.m = np.ascontiguousarray(m, dtype=np.float32)

    def __len__(self) -> int:
        return int(self.m.shape[0])

    def __matmul__(self, q: Sequence[float]) -> np.ndarray:
        return self.m @ np.asarray(q, dtype=np.float32)

    def row(self, i: int) -> list[float]:
        return self.m[i].tolist()


def load_npy(path: Path) -> VectorMatrix:
    """读二维 float16 / float32 的 .npy。别的格式直接报错。"""
    m = np.load(path, allow_pickle=False)
    if m.ndim != 2:
        raise ValueError(f"向量文件不是二维的：{m.shape}")
    if m.dtype not in (np.float16, np.float32):
        raise ValueError(f"向量类型不支持：{m.dtype}")
    return VectorMatrix(m)


class EmbedError(RuntimeError):
    pass


class RemoteEmbedder:
    """远程查询向量。

    - 一次搜索要的几句话一个请求发过去（小服务一次算一句，约 0.5 秒一句，并发也不会更快）。
      超时 = max(基础超时, 每句超时 × 句数)：一句 2 秒，五句 4 秒（默认值）。
    - 连着失败 2 次，60 秒内不再请求（直接只用关键词），免得小服务挂了每次搜索都白等。
    - 结果按原文缓存，同一句话不算第二遍。
    """

    FAILS_TO_PAUSE = 2
    PAUSE_SECONDS = 60.0

    def __init__(
        self,
        url: str,
        instruct: str,
        *,
        timeout: float = 2.0,
        per_text_timeout: float = 0.8,
        cache_size: int = 4096,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = url.rstrip("/") + "/embed"
        self.instruct = instruct
        self.timeout = timeout
        self.per_text_timeout = per_text_timeout
        self._client = httpx.Client(trust_env=False, timeout=timeout, transport=transport)
        self._cache: OrderedDict[str, QueryVector] = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()
        self._fails = 0
        self._paused_until = 0.0

    def cached(self, text: str) -> QueryVector | None:
        with self._lock:
            v = self._cache.get(text)
            if v is not None:
                self._cache.move_to_end(text)
            return v

    def _remember(self, text: str, vec: QueryVector) -> None:
        with self._lock:
            self._cache[text] = vec
            self._cache.move_to_end(text)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)

    @property
    def paused(self) -> bool:
        return time.monotonic() < self._paused_until

    def _request(self, texts: list[str]) -> list[QueryVector]:
        if self.paused:
            raise EmbedError("向量小服务刚才连着失败，暂停请求一分钟")
        read = max(self.timeout, self.per_text_timeout * len(texts))
        try:
            r = self._client.post(
                self.url,
                json={"texts": texts, "instruct": self.instruct},
                timeout=httpx.Timeout(read, connect=min(1.0, read)),
            )
            r.raise_for_status()
            vecs = [_qv(v) for v in r.json()["vectors"]]
            if len(vecs) != len(texts):
                raise ValueError("返回的向量条数不对")
        except Exception as e:  # 超时、连不上、返回不对，一律算失败
            with self._lock:
                self._fails += 1
                if self._fails >= self.FAILS_TO_PAUSE:
                    self._paused_until = time.monotonic() + self.PAUSE_SECONDS
            raise EmbedError(f"{type(e).__name__}: {str(e)[:120]}") from e
        with self._lock:
            self._fails = 0
        for t, v in zip(texts, vecs):
            self._remember(t, v)
        return vecs

    def embed_one(self, text: str) -> QueryVector:
        hit = self.cached(text)
        return hit if hit is not None else self._request([text])[0]

    def embed_many(self, texts: Iterable[str]) -> dict[str, QueryVector | None]:
        """几句话一起算。失败时这几句都是 None（缓存里有的照样给）。"""
        todo = list(dict.fromkeys(texts))
        out: dict[str, QueryVector | None] = {t: self.cached(t) for t in todo}
        missing = [t for t, v in out.items() if v is None]
        if missing:
            try:
                for t, v in zip(missing, self._request(missing)):
                    out[t] = v
            except EmbedError as e:
                log.warning("向量小服务没算出来（%d 句），这次搜索只用关键词：%s", len(missing), e)
        return out

    # 引擎的 _qvec 这样调：M.encode([txt], prompt=QINST, normalize_embeddings=True)[0].astype("float32")
    def encode(self, texts: Sequence[str], prompt: str | None = None, normalize_embeddings: bool = True):
        return [self.embed_one(t) for t in texts]

    def close(self) -> None:
        self._client.close()
