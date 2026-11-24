"""拆词：最长匹配、空格隔开的短词原样留、一个都没对上时按标点切、口语虚词去掉、最多 8 个。"""

from app.figures.textsplit import MAX_WORDS, split_query
from tests.figures.conftest import needs_engine

VOCAB = {"中介", "调节", "有调节的中介", "问卷", "睡眠", "假设模型", "试次流程", "被试内", "实验", "fnirs", "交叉滞后"}


def test_longest_match_prefers_longer_term():
    sp = split_query("有调节的中介模型怎么画", VOCAB)
    assert sp.words[0] == "有调节的中介"
    assert "中介" not in sp.words and "调节" not in sp.words


def test_sentence_drops_fillers():
    sp = split_query("我做的是手机依赖和睡眠的问卷研究，想画假设模型", VOCAB)
    assert {"睡眠", "问卷", "假设模型"} <= set(sp.words)
    for junk in ("我", "想画", "的", "研究", "做的是"):
        assert junk not in sp.words
    assert sp.matched == [w for w in sp.words if w in {"睡眠", "问卷", "假设模型"}]


def test_space_separated_short_words_kept_as_typed():
    sp = split_query("交叉滞后 CLPM 两个时间点 两个变量", VOCAB)
    assert sp.words == ["交叉滞后", "CLPM", "两个时间点", "两个变量"]


def test_original_case_kept():
    sp = split_query("功能性近红外 fNIRS 的光极排布图", VOCAB)
    assert "fNIRS" in sp.words
    assert "功能性近红外" in sp.words


def test_fallback_when_nothing_matches():
    sp = split_query("沙盘游戏，箱庭疗法", VOCAB)
    assert sp.fallback is True
    assert sp.words == ["沙盘游戏", "箱庭疗法"]


def test_at_most_eight_words_and_vocab_first():
    text = " ".join(["中介", "调节", "问卷", "睡眠", "实验", "被试内"] + [f"词{i}词" for i in range(6)])
    sp = split_query(text, VOCAB)
    assert len(sp.words) == MAX_WORDS
    assert {"中介", "调节", "问卷", "睡眠", "实验", "被试内"} <= set(sp.words)


def test_empty():
    assert split_query("   ", VOCAB).words == []


@needs_engine
def test_real_vocab(engine):
    sp = engine.split("被试内实验的试次流程")
    assert sp.words == ["被试内", "实验", "试次流程"]
    sp = engine.split("我做的是手机依赖和睡眠的问卷研究，想画假设模型")
    assert {"睡眠", "问卷", "假设模型"} <= set(sp.words)
