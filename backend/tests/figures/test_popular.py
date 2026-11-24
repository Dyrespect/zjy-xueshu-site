"""首页「常见要画的」：每个词点进去，这一类要有 ≥ 8 张结果（任务单要求写测试保证）。"""

import pytest

from app.figures.engine import is_relevant
from app.figures.popular import POPULAR
from tests.figures.conftest import needs_engine

pytestmark = needs_engine

EXPECTED_TYPE = {
    "假设模型": "W2",
    "中介和调节": "W2",
    "试次流程": "D2",
    "技术路线": "W3",
    "被试筛选流程": "P1",
    "测量时间线": "D3",
    "结果图·交互作用": "R2",
    "网络图": "R9",
}


@pytest.mark.parametrize(("label", "query"), POPULAR)
def test_each_popular_word_has_at_least_8(engine, label, query):
    res = engine.full_search(query)
    assert res.main is not None
    in_type = [r for r in res.main.same if is_relevant(r) and (res.code == "任意" or r["类"] in ("主", "次"))]
    assert len(in_type) >= 8, f"「{label}」点进去这一类只有 {len(in_type)} 张"
    if label in EXPECTED_TYPE:
        assert res.code == EXPECTED_TYPE[label], f"「{label}」猜成了 {res.code}"


def test_popular_words_exist_in_library(engine):
    for label, query in POPULAR:
        words = engine.split(query).words
        assert words, label
        assert any(engine.word_hits(w) for w in words), f"「{label}」库里一张都对不上"
