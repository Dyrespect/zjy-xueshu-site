"""拆词：把用户的一句话变成找图引擎要的关键词（最多 8 个）。

PRD 第三节 P0-2 第 2 步：用库里出现过的词（方法范式、手段、画面上有什么、结构、讲的是什么里的词，
加上引擎 SYN 的键和图型名）对这句话做最长匹配；一个词都没对上，就把整句按标点和空格切开交过去。

另外两条（我加的，理由写在旁边）：
- 用户自己用空格隔开的短词（「交叉滞后 CLPM 两个时间点」）原样保留，不再拆：这是给 agent 写词的
  写法，拆开反而跟直接跑 查参考.py 的结果对不上。
- 对不上词表的剩余部分（「光极排布图」）去掉口语虚词后也交过去：引擎会数出它全库 0 张，
  页面才能说「库里没有『光极排布图』」，再去补找相近的。
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass

MAX_WORDS = 8
MAX_TERM_LEN = 16
KEEP_WHOLE_LEN = 6  # 没有口语虚词、不超过这么长的一段，当成用户自己写好的一个词

# 切段：空白和标点（不切 - 和 ×：cross-lagged、2×2 是一个词）
_SPLIT = re.compile(r"[\s，。、；：！？,.;:!?()（）\[\]【】{}「」『』“”\"'‘’/\\|<>《》~～·…—–+=*#@&^%$]+")

# 口语虚词：出现在一段里，说明这段是句子不是词，要拆；拆剩下的部分里也要去掉它们
_FILLER = re.compile(
    "我们|我|想要|想|需要|请问|请|帮我|帮忙|怎么画|怎么|如何|画一张|画一个|画个|画出|画|"
    "做一张|做一个|做的是|做了|做|一张|一个|一下|有没有|有什么|什么样的|什么|这种|那种|这个|那个|"
    "这类|那类|关于|用来|用于|用的是|用了|的是|是|的|和|与|及|或者|还有|以及|里面|看看|找|吗|呢|吧|啊|要|"
    "在哪里|在哪|哪里|放在|贴在|位于|上面|下面|旁边|怎样|怎么样"
)

# 拆剩下、单独成词也没意义的（场合、泛称）
_STOP = {
    "研究", "论文", "文章", "汇报", "组会", "开题", "中期", "答辩", "ppt", "图", "图片", "图表", "示意图",
    "示意", "流程图", "模型", "数据", "结果", "内容", "东西", "方面", "部分", "参考", "例子", "样子", "好看",
    "一些", "相关", "类似", "那样", "这样", "其中", "我的", "老师", "导师", "同学", "硕士", "博士", "研究生",
    "头上", "身上", "手上", "一起", "分别", "之后", "之前", "时候",
}


def _norm(t: str) -> str:
    return t.strip().lower()


def _valid_term(t: str) -> bool:
    return 2 <= len(t) <= MAX_TERM_LEN and not re.fullmatch(r"[\d\W_]+", t)


def build_vocab(docs: Iterable[dict], names: dict[str, str], syn_keys: Iterable[str], min_df: int = 2) -> set[str]:
    """库里出现过的词（至少 min_df 张图用过），加 SYN 的键、图型名和图型名里「与」「和」两边的部分。"""
    df: Counter[str] = Counter()
    for d in docs:
        h = d["h"]
        seen: set[str] = set()
        for k in ("方法范式", "手段", "画面上有什么", "结构", "研究的情况"):
            for t in h.get(k) or []:
                t = _norm(t)
                if _valid_term(t):
                    seen.add(t)
        what = _norm(h.get("讲的是什么") or "")
        for piece in re.split(r"[、，,；;/（）()\s]+|与|和|及", what):
            if _valid_term(piece):
                seen.add(piece)
        df.update(seen)
    vocab = {t for t, c in df.items() if c >= min_df}
    for k in syn_keys:
        vocab.add(_norm(k))
    for name in names.values():
        vocab.add(_norm(name))
        for part in re.split("[与和]", name):
            if len(part) >= 3:
                vocab.add(_norm(part))
    return {t for t in vocab if _valid_term(t) and t not in _STOP}


@dataclass
class Split:
    words: list[str]  # 交给引擎的词（按句子里出现的先后）
    matched: list[str]  # 其中对上词表的
    fallback: bool  # 一个词都没对上，按标点空格切的


def _is_ascii_word_char(ch: str) -> bool:
    return ch.isascii() and (ch.isalnum() or ch == "-")


def _clean_leftover(buf: str) -> list[str]:
    out = []
    for chunk in buf.split():
        for piece in _FILLER.split(chunk):
            piece = piece.strip("-")
            if _valid_term(piece) and piece not in _STOP:
                out.append(piece)
    return out


def _longest_match(seg: str, vocab: set[str], maxlen: int) -> list[tuple[str, bool]]:
    """在一段里从左往右找最长的词表词；对不上的字攒起来，去掉虚词后也留下（标记为没对上）。"""
    out: list[tuple[str, bool]] = []
    buf = ""
    i, n = 0, len(seg)
    while i < n:
        hit = ""
        if _is_ascii_word_char(seg[i]):
            j = i
            while j < n and _is_ascii_word_char(seg[j]):
                j += 1
            run = seg[i:j]
            if run in vocab:
                hit = run
            else:
                # 英文词整个对不上，整体当剩余部分（不拆字母）
                buf += " " + run + " "
                i = j
                continue
        else:
            for L in range(min(maxlen, n - i), 1, -1):
                cand = seg[i : i + L]
                if cand in vocab and not (_is_ascii_word_char(cand[-1]) and i + L < n and _is_ascii_word_char(seg[i + L])):
                    hit = cand
                    break
        if hit:
            for w in _clean_leftover(buf):
                out.append((w, False))
            buf = ""
            out.append((hit, True))
            i += len(hit)
        else:
            buf += seg[i]
            i += 1
    for w in _clean_leftover(buf):
        out.append((w, False))
    return out


def split_query(text: str, vocab: set[str], hits: Callable[[str], int] | None = None) -> Split:
    """hits(词) = 全库有几张图对上这个词（引擎的算法）。给了它，没对上词表、全库又 0 张的一段
    （「功能性近红外」）再按词表拆一次，留下拆出来的词表词（「近红外」）：免得把库里其实有的东西
    说成「库里没有」。拆不出词表词的（「箱庭疗法」）原样留着，页面会说库里没有它。"""
    text = (text or "").strip()[:200]
    if not text:
        return Split([], [], False)
    maxlen = min(MAX_TERM_LEN, max((len(t) for t in vocab), default=2))
    pieces: list[tuple[str, bool]] = []
    for seg in _SPLIT.split(_norm(text)):
        if not seg:
            continue
        if seg in vocab:
            pieces.append((seg, True))
        elif not _FILLER.search(seg) and len(seg) <= KEEP_WHOLE_LEN:
            if _valid_term(seg) and seg not in _STOP:
                pieces.append((seg, False))
        else:
            pieces.extend(_longest_match(seg, vocab, maxlen))

    if hits is not None:
        rescued: list[tuple[str, bool]] = []
        for w, ok in pieces:
            if not ok and hits(w) == 0:
                inner = [x for x in _longest_match(w, vocab, maxlen) if x[1]]
                if inner:
                    rescued.extend(inner)
                    continue
            rescued.append((w, ok))
        pieces = rescued

    matched_any = any(ok for _, ok in pieces)
    if not matched_any:
        # 一个词都没对上：整句按标点和空格切开交过去（去掉口语虚词）
        pieces = []
        for seg in _SPLIT.split(_norm(text)):
            pieces.extend((w, False) for w in _clean_leftover(seg))

    seen: set[str] = set()
    uniq: list[tuple[int, str, bool]] = []
    for pos, (w, ok) in enumerate(pieces):
        if w not in seen:
            seen.add(w)
            uniq.append((pos, w, ok))
    if len(uniq) > MAX_WORDS:  # 超了先留对上词表的
        keep = sorted(uniq, key=lambda x: (not x[2], x[0]))[:MAX_WORDS]
        uniq = sorted(keep, key=lambda x: x[0])
    # 交出去的词用用户原来的大小写（fNIRS、CLPM）：匹配时一律小写，最后按位置还原
    low = text.lower()

    def orig(w: str) -> str:
        i = low.find(w)
        return text[i : i + len(w)] if i >= 0 and len(low) == len(text) else w

    words = [orig(w) for _, w, _ in uniq]
    matched = [orig(w) for _, w, ok in uniq if ok]
    return Split(words=words, matched=matched, fallback=not matched_any)
