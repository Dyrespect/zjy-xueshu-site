"""找图引擎的接线：加载 `查参考.py`（只读调用，不复制它的找法），把远程查询向量接进它的 `_VEC`。

- 进程启动时加载一次（`load_engine`），之后所有请求共用。引擎里有全局状态（`_VEC`、`_CACHE`），
  所以调它的地方一律拿 `self.lock`（一次搜索零点几秒，排队也够每天几百次）。
- 语义一半：`_VEC` 里放 `V`（图库向量）、`M`（远程编码器）、`状态="能用"`。每次搜索前先把这次要用的
  查询向量并行算好塞进 `_VEC` 的缓存位（键和引擎 `_qvec` 的一样），搜完拿掉。小服务连不上 / 超时，
  这次搜索把 `_VEC["状态"]` 临时设成一句说明（引擎就只按关键词找），搜完复原——一次失败不会让
  整个进程变成只用关键词。
- 不往「学术汇报」目录里写任何东西：加载时关掉 .pyc 缓存（sys.dont_write_bytecode）。
"""

from __future__ import annotations

import collections
import importlib.util
import json
import logging
import re
import sys
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

from app.figures.textsplit import Split, build_vocab, split_query
from app.figures.vectors import EmbedError, RemoteEmbedder, VectorMatrix, load_npy

log = logging.getLogger("app.figures.engine")

ENGINE_FILE = "查参考.py"
GUESS_TOP = 20  # 猜图型：看「任意」找出来的前 20 张
GUESS_SHARE = 0.15  # 票最多的图型不到总票数的这么多，算「前 20 张很散」，用「任意」
VEC_EVIDENCE = 200  # 向量名次在全库前 200：引擎 _fuse 里也用这条线判断「沾不沾边」

Key = tuple[str, tuple[str, ...]]


def load_engine_module(engine_path: Path) -> ModuleType:
    path = engine_path / ENGINE_FILE if engine_path.is_dir() else engine_path
    if not path.is_file():
        raise FileNotFoundError(f"找不到找图引擎：{path}")
    spec = importlib.util.spec_from_file_location("figures_chacankao", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"加载不了找图引擎：{path}")
    mod = importlib.util.module_from_spec(spec)
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # 不在引擎目录里写 __pycache__
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = old
    return mod


@dataclass
class FindRun:
    """一次 find / search 的结果（引擎原样的行，外面再挑字段给页面）。"""

    code: str
    in_type: int
    same: list[dict]
    other: list[dict]
    word_stat: dict[str, dict[str, int]]
    used_vectors: bool


@dataclass
class EngineSearch:
    split: Split
    guess: str | None  # 猜出来的图型；猜不出 None
    code: str  # 实际用的（图型代码或「任意」）
    main: FindRun | None
    extras: list[tuple[str, str, list[dict]]] = field(default_factory=list)  # (key, 标题, 行)
    zero_words: list[str] = field(default_factory=list)
    word_counts: dict[str, int] = field(default_factory=dict)
    used_vectors: bool = False
    vector_note: str = ""


class FigureEngine:
    def __init__(
        self,
        module: ModuleType,
        docs: list[dict],
        vectors: VectorMatrix | None,
        embedder: RemoteEmbedder | None,
        vector_note: str = "",
    ) -> None:
        self.E = module
        self.docs = docs
        self.index = {d["号"]: i for i, d in enumerate(docs)}
        self.names: dict[str, str] = dict(module.NAMES)
        self.near: dict[str, list[str]] = dict(module.NEAR)
        self.lock = threading.RLock()
        self.vectors = vectors
        self.embedder = embedder if vectors is not None else None
        self.vector_note = vector_note
        if self.vectors is not None and self.embedder is not None:
            module._VEC.update(V=self.vectors, M=self.embedder, 状态="能用")
        else:
            module._VEC["状态"] = f"没用上语义检索：{vector_note or '没配向量小服务'}"
        self.vocab = build_vocab(docs, self.names, module.SYN.keys())
        self._type_parts = self._build_type_parts()
        with self.lock:
            module._ctx(docs)  # 全库词频先算好

    # ---- 基础 ----
    @property
    def semantic(self) -> bool:
        return self.vectors is not None and self.embedder is not None

    def norm_code(self, code: str | None) -> str:
        c = (code or "").upper()
        return c if c in self.names else "任意"

    def key(self, code: str | None, words: Sequence[str]) -> Key | None:
        """跟引擎 _qvec 用的缓存键一模一样：(图型或「任意」, 词)。没有词时引擎不算向量。"""
        ws = tuple(w for w in words if w.strip())
        return (self.norm_code(code), ws) if ws else None

    def key_text(self, key: Key) -> str:
        code, ws = key
        return (self.names[code] + "：" if code in self.names else "") + " ".join(ws)

    def doc(self, fid: int) -> dict | None:
        i = self.index.get(fid)
        return None if i is None else self.docs[i]

    def word_hits(self, word: str) -> set[int]:
        with self.lock:
            hh, hc = self.E._hits(self.docs, word)
        return hh | hc

    def split(self, text: str) -> Split:
        return split_query(text, self.vocab, hits=lambda w: len(self.word_hits(w)))

    # ---- 状态切换（都在 self.lock 里用）----
    @contextmanager
    def _keyword_only(self, why: str) -> Iterator[None]:
        vec = self.E._VEC
        old = vec.get("状态")
        vec["状态"] = why
        try:
            yield
        finally:
            vec["状态"] = old

    @contextmanager
    def _with_query_vectors(self, qvecs: dict[Key, Any], live: bool) -> Iterator[None]:
        """把算好的查询向量塞进引擎的缓存位；live=False 时没算好的键不许现场去算（直接报错，外面改用关键词）。"""
        vec = self.E._VEC
        vec.update(qvecs)
        old_m = vec.get("M")
        if not live:
            vec["M"] = _NoLiveEncoder()
        try:
            yield
        finally:
            vec["M"] = old_m
            for k in [k for k in vec if isinstance(k, tuple)]:
                del vec[k]
            hit = self.E._ctx(self.docs)["hit"]
            if len(hit) > 5000:  # 引擎按词缓存命中的图，长期跑会一直涨
                hit.clear()

    # ---- 猜图型 ----
    def _build_type_parts(self) -> dict[str, str]:
        parts: dict[str, str] = {}
        for code, name in self.names.items():
            for p in [name, *re.split("[与和]", name)]:
                if len(p) >= 3:
                    parts.setdefault(p.lower(), code)
        return parts

    def explicit_types(self, text: str) -> list[str]:
        """句子里直接写了的图型名（「技术路线」「试次流程」「假设模型」），按出现的先后。"""
        t = text.lower()
        hits = sorted((t.find(p), c) for p, c in self._type_parts.items() if p in t)
        return list(dict.fromkeys(c for _, c in hits))

    def explicit_type(self, text: str) -> str | None:
        codes = self.explicit_types(text)
        return codes[0] if len(codes) == 1 else None

    def type_votes(self, words: list[str]) -> collections.Counter[str]:
        """用「任意」按这些词找一遍（只用关键词），前 20 张按名次加权投票：越靠前分越高，次图型算半票。"""
        with self.lock, self._keyword_only("猜图型只用关键词"):
            res = self.E.search(self.docs, "任意", words, n=GUESS_TOP, m=0)
        votes: collections.Counter[str] = collections.Counter()
        for i, r in enumerate(res["这一类"][:GUESS_TOP]):
            if r["字分"] <= 0:
                continue
            w = 1 / (1 + i / 5)
            votes[r["d"]["h"]["主图型"]] += w
            for c in r["d"]["h"].get("次图型") or []:
                votes[c] += 0.5 * w
        return votes

    def guess_type(self, words: list[str], text: str) -> str | None:
        """PRD：先用「任意」按这句话找一遍，取前 20 张里最多的主图型；很散就猜不出（返回 None，用「任意」）。
        - 句子里直接写了图型名：只写了一种就用它；写了几种，在这几种里按投票选（票一样取先写的）。
        - 投票按名次加权、次图型算半票；最多的那个不到总票数的 15% 才算「很散」。
        只用关键词猜（省掉一趟远程向量）：拿 118 道考卷题试过，带不带向量猜对的一样多（79 道），猜错了页面上能改。"""
        explicit = self.explicit_types(text)
        if len(explicit) == 1:
            return explicit[0]
        if not words:
            return explicit[0] if explicit else None
        votes = self.type_votes(words)
        if explicit:
            return max(explicit, key=lambda c: (votes.get(c, 0.0), -explicit.index(c)))
        if not votes:
            return None
        top, n1 = votes.most_common(1)[0]
        return top if n1 >= GUESS_SHARE * sum(votes.values()) else None

    # ---- 预测这次要用哪些查询向量 ----
    def predict_find_keys(self, code: str, words: list[str]) -> set[Key]:
        E, docs = self.E, self.docs
        loose = list(dict.fromkeys(w for w in words if w.strip()))
        with self.lock:
            cls = E.classify(docs, loose) if loose else {}
        S = [w for w in loose if cls[w] == "画法"]
        M = [w for w in loose if cls[w] == "方法"]
        base = S or [self.names.get(code, "")]
        angles: list[list[str]] = [loose] + [[w, *S] for w in M[:3]] + [base]
        keys = {self.key(code, ws) for ws in angles}
        if code in self.names:
            if S:
                keys.add(self.key("任意", S))
            inn = {d["号"] for d in docs if d["h"]["主图型"] == code or code in d["h"]["次图型"]}
            for w in S + M:
                allc = self.word_hits(w)
                if not (allc & inn) and allc and not E.LAYOUT.search(w) and (w in S or len(allc) <= E.MISS_M_MAX):
                    keys.add(self.key("任意", [w]))
        keys.discard(None)
        return keys  # type: ignore[return-value]

    def prefetch(self, keys: set[Key]) -> dict[Key, Any]:
        """并行去小服务算这些查询向量；算不出来的不在返回里。"""
        if not self.semantic or not keys:
            return {}
        assert self.embedder is not None
        texts = {k: self.key_text(k) for k in keys}
        got = self.embedder.embed_many(texts.values())
        return {k: got[t] for k, t in texts.items() if got.get(t) is not None}

    # ---- 跑引擎 ----
    def _run(self, fn, qvecs: dict[Key, Any], need: set[Key], live: bool) -> tuple[Any, bool]:
        """有向量就带向量跑；需要的键没算出来、或者现场去算失败了，就这一次只用关键词再跑。"""
        if self.semantic and need <= qvecs.keys():
            try:
                with self._with_query_vectors(qvecs, live=live):
                    return fn(), True
            except (EmbedError, _NoLiveVector) as e:
                log.warning("向量没用上，这次只按关键词找：%s", e)
        with self._with_query_vectors({}, live=False), self._keyword_only("这次只按关键词找"):
            return fn(), False

    def find(
        self, code: str, words: list[str], qvecs: dict[Key, Any], need: set[Key] | None = None, n: int = 16, m: int = 4
    ) -> FindRun:
        """引擎的 find（分几路找再合并）。need = 这次预测要用的查询向量，缺一个就整次只用关键词。"""
        if need is None:
            need = self.predict_find_keys(code, words) if self.semantic else set()
        # 引擎偶尔会要一个预测之外的向量，允许现场去算（有超时，失败就整次只用关键词）
        with self.lock:
            res, used = self._run(lambda: self.E.find(self.docs, code, words, n=n, m=m), qvecs, need, live=True)
        return FindRun(res["图型"], res["门里"], list(res["这一类"]), list(res["别的类"]), dict(res["词"]), used)

    def search_one(self, code: str, words: list[str], qvecs: dict[Key, Any], n: int = 24) -> list[dict]:
        """单路找（补找的几组用）：向量算好了就用，没算好就只按关键词，不现场去算。"""
        k = self.key(code, words)
        need = {k} if k else set()
        with self.lock:
            res, _ = self._run(lambda: self.E.search(self.docs, code, words, n=n, m=0), qvecs, need, live=False)
        return list(res["这一类"])

    # ---- 更多类似的 ----
    def similar(self, fid: int, k: int = 8) -> list[dict]:
        i = self.index.get(fid)
        if i is None:
            return []
        me = self.docs[i]
        if self.vectors is not None:
            scores = self.vectors @ self.vectors.row(i)
            order = sorted(range(len(scores)), key=lambda j: -scores[j])
        else:  # 没有向量：同图型里，标签词重合最多的
            mine = _tag_set(me)
            same = [j for j, d in enumerate(self.docs) if d["h"]["主图型"] == me["h"]["主图型"]]
            order = sorted(same, key=lambda j: -len(mine & _tag_set(self.docs[j])))
        out: list[dict] = []
        papers = {me["题目"]}
        ids = {me["号"]} | set(me["重复件"])
        for j in order:
            d = self.docs[j]
            if d["号"] in ids or d["题目"] in papers or (d["重复件"] & ids):
                continue
            papers.add(d["题目"])
            ids.add(d["号"])
            out.append(d)
            if len(out) >= k:
                break
        return out

    # ---- 一整次搜索（页面用）----
    def full_search(self, text: str, code_override: str | None = None) -> EngineSearch:
        sp = self.split(text)
        words = sp.words
        guess = None
        if code_override:
            code = self.norm_code(code_override)
        else:
            guess = self.guess_type(words, text)
            code = guess or "任意"
        out = EngineSearch(split=sp, guess=guess, code=code, main=None, vector_note=self.vector_note)
        if not words:
            return out
        counts = {w: len(self.word_hits(w)) for w in words}
        # 图型名（「样本构成」）不在标签里、数出来是 0，但库里这类图有的是：不算「库里没有」
        zero = [w for w in words if counts[w] == 0 and w.lower() not in self._type_parts]
        rest = [w for w in words if w not in zero]
        out.word_counts, out.zero_words = counts, zero

        keys: set[Key] = set()
        need: set[Key] = set()
        if self.semantic:
            need = self.predict_find_keys(code, words)
            keys = set(need)
            if zero:  # 补找的几组也提前算好向量（去掉这个词 / 上一层的说法 / 相邻图型）
                near = self.near.get(code) or []
                if rest:
                    keys.add(self.key(code, rest))  # type: ignore[arg-type]
                if code in self.names and self.names[code] not in words:
                    keys.add(self.key(code, [self.names[code], *rest]))  # type: ignore[arg-type]
                if near:
                    keys.add(self.key(near[0], rest or [self.names[near[0]]]))  # type: ignore[arg-type]
            keys.discard(None)  # type: ignore[arg-type]
        qvecs = self.prefetch(keys)

        out.main = self.find(code, words, qvecs, need=need)
        out.used_vectors = out.main.used_vectors
        if not out.used_vectors and self.semantic:
            qvecs = {}  # 主搜索都没用上向量，补找的几组也别用，免得一页里两种找法
        shown = {r["d"]["号"] for r in out.main.same + out.main.other}
        papers = {r["d"]["题目"] for r in out.main.same + out.main.other}

        def extra(key: str, title: str, rows: list[dict], limit: int = 8) -> None:
            picked = []
            for r in rows:
                d = r["d"]
                if d["号"] in shown or d["题目"] in papers or not _relevant(r):
                    continue
                shown.add(d["号"])
                papers.add(d["题目"])
                picked.append(r)
                if len(picked) >= limit:
                    break
            if picked:
                out.extras.append((key, title, picked))

        if zero:
            if rest:
                extra("去掉", "去掉「" + "」「".join(zero) + "」再找", self.search_one(code, rest, qvecs))
            # 上一层的说法 = 这一类图的名字（PRD 的例子：「眼动」→「实验流程」）。
            # 试过用向量找「最近的方法词」，出来的常不相干（「房树人」→「Venn diagram」），没用。
            if code in self.names and self.names[code] not in words:
                up = self.names[code]
                extra("上一层", f"换成上一层的说法「{up}」", self.search_one(code, [up, *rest], qvecs))
            near = self.near.get(code) or []
            if near:
                base = rest or [self.names[near[0]]]
                extra("相邻", f"相邻的图型：{self.names[near[0]]}", self.search_one(near[0], base, qvecs))

        in_type = [r for r in out.main.same if r["类"] in ("主", "次") and _relevant(r)]
        if code in self.names and len(in_type) < 6 and not any(k == "相邻" for k, _, _ in out.extras):
            near = self.near.get(code) or []
            if near:
                extra("相邻", f"相邻的图型：{self.names[near[0]]}", self.search_one(near[0], words, qvecs))
        return out


class _NoLiveVector(RuntimeError):
    pass


class _NoLiveEncoder:
    def encode(self, texts, prompt=None, normalize_embeddings=True):
        raise _NoLiveVector("这一组的查询向量没提前算好")


def _relevant(r: dict) -> bool:
    """引擎排出来的行里，跟这句话真沾边的：对上了词，或关键词有分，或向量名次在全库前 200。
    （没有词、又没有向量时，引擎会按期刊档次排一串不相干的图，这些不给人看。）"""
    return bool(r.get("对上的词")) or r.get("字分", 0) > 0 or r.get("向量名次", 10**9) < VEC_EVIDENCE


def is_relevant(r: dict) -> bool:
    return _relevant(r)


def _tag_set(d: dict) -> set[str]:
    h = d["h"]
    return {t for k in ("方法范式", "手段", "画面上有什么", "结构", "研究的情况") for t in (h.get(k) or [])}


def load_engine(
    engine_path: Path,
    *,
    embed_url: str = "",
    embed_timeout: float = 2.0,
    embedder: RemoteEmbedder | None = None,
) -> FigureEngine:
    """加载引擎、索引、图库向量。向量文件缺了或和索引对不上：照样能用，只按关键词找。"""
    mod = load_engine_module(engine_path)
    docs = mod.load()
    vectors: VectorMatrix | None = None
    note = ""
    try:
        meta = json.loads(Path(mod.VEC_META).read_text(encoding="utf-8"))
        if meta.get("号") != [d["号"] for d in docs]:
            raise ValueError("向量和索引对不上（索引重编过，向量没重编）")
        vectors = load_npy(Path(mod.VEC_PATH))
        if len(vectors) != len(docs):
            raise ValueError("向量条数和索引对不上")
    except Exception as e:
        vectors = None
        note = f"图库向量读不了：{str(e)[:100]}"
        log.warning("%s；搜索只用关键词，「更多类似的」按标签词找", note)
    if embedder is None and embed_url and vectors is not None:
        embedder = RemoteEmbedder(embed_url, mod.QINST, timeout=embed_timeout)
    if embedder is None and not note:
        note = "没配向量小服务（EMBED_URL）"
    return FigureEngine(mod, docs, vectors, embedder, note)
