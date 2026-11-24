"""找图引擎接线：猜图型、0 张词的补找、跟直接调引擎的结果一致、不往学术汇报目录写东西。"""

import pytest

from app.figures.engine import is_relevant
from tests.figures.conftest import ENGINE_PATH, needs_engine

pytestmark = needs_engine


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("被试内实验的试次流程", "D2"),
        ("开题的技术路线图", "W3"),
        ("我做的是手机依赖和睡眠的问卷研究，想画假设模型", "W2"),
        ("症状网络 中心性 网络分析", "R9"),
        ("样本筛选 纳入排除 人数", "P1"),
    ],
)
def test_guess_type(engine, text, code):
    sp = engine.split(text)
    assert engine.guess_type(sp.words, text) == code


def test_explicit_type_name_wins(engine):
    assert engine.explicit_type("我要画测量时间线") == "D3"
    assert engine.explicit_type("技术路线和试次流程") is None  # 写了两种，不替用户定


def test_guess_gives_up_when_scattered(engine):
    # 只有一个很泛的词：前 20 张散在好几种图型里，猜不出就用「任意」
    assert engine.guess_type(["青少年"], "青少年") is None


def test_same_results_as_calling_engine_directly(engine):
    """网站不另写找法：同样的图型和词，跟直接调 查参考.py 的 find() 一模一样（不连向量时）。"""
    words = ["交叉滞后", "CLPM", "两个时间点", "两个变量", "路径图"]
    mine = engine.find("A2", words, {}, need=set())
    with engine.lock:
        direct = engine.E.find(engine.docs, "A2", words, n=16, m=4)
    assert [r["d"]["号"] for r in mine.same] == [r["d"]["号"] for r in direct["这一类"]]
    assert [r["d"]["号"] for r in mine.other] == [r["d"]["号"] for r in direct["别的类"]]


@pytest.mark.parametrize(
    ("text", "missing"),
    [
        ("沙盘游戏治疗的流程", "沙盘"),
        ("催眠诱导的流程", "催眠诱导"),
        ("绘画投射测验 房树人", "房树人"),
    ],
)
def test_zero_word_gets_nearby_groups(engine, text, missing):
    res = engine.full_search(text)
    assert missing in res.zero_words
    assert res.word_counts[missing] == 0
    assert res.extras, "库里没有的词要补找相近的几组"
    keys = {k for k, _, _ in res.extras}
    assert keys & {"去掉", "相近", "上一层", "相邻"}
    shown = [r["d"]["号"] for r in res.main.same + res.main.other] + [r["d"]["号"] for _, _, rows in res.extras for r in rows]
    assert len(shown) == len(set(shown)), "补找的组不重复已经出过的图"


def test_compound_with_known_part_is_not_called_missing(engine):
    """「功能性近红外」原样全库 0 张，但库里有「近红外」的光极排布图：拆出「近红外」去找，不说库里没有。"""
    res = engine.full_search("功能性近红外 fNIRS 的光极排布图")
    assert "近红外" in res.split.words and res.zero_words == []
    titles = [r["d"]["h"]["讲的是什么"] for r in res.main.same[:8]]
    assert sum("光极" in t or "近红外" in t or "fNIRS" in t for t in titles) >= 4


def test_type_name_is_not_missing(engine):
    res = engine.full_search("三组人数 样本构成")
    assert "样本构成" in res.split.words and "样本构成" not in res.zero_words


def test_few_results_adds_neighbor_type(engine):
    # 只写一个这一类里很少对上的词：结果少于 6 张时补「相邻图型」一组
    res = engine.full_search("实验材料 量表条目", code_override="W7")
    in_type = [r for r in res.main.same if r["类"] in ("主", "次") and is_relevant(r)]
    if len(in_type) < 6 and engine.near.get("W7"):
        assert any(k == "相邻" for k, _, _ in res.extras)


def test_keyword_only_when_no_vectors(engine):
    assert not engine.semantic
    res = engine.full_search("有调节的中介模型")
    assert res.used_vectors is False
    assert res.main is not None and len(res.main.same) == 16


def test_similar_are_different_papers(engine):
    fid = engine.docs[0]["号"]
    sims = engine.similar(fid, k=8)
    assert len(sims) == 8
    titles = [d["题目"] for d in sims]
    assert len(set(titles)) == 8
    assert engine.docs[0]["题目"] not in titles


def test_no_bytecode_written_into_engine_dir():
    pyc = ENGINE_PATH / "__pycache__"

    def snapshot():
        return {(p.name, p.stat().st_mtime_ns) for p in pyc.iterdir()} if pyc.is_dir() else set()

    before = snapshot()
    from app.figures.engine import load_engine_module

    load_engine_module(ENGINE_PATH)
    assert snapshot() == before
