"""本模块的节点都登记了、说明卡齐全、后台节点目录能看到；check.py 规矩 11（说明卡里的字不算发给平台的）和规矩 15 会失败。"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.nodes import all_cards, has_handler
from app.registry import import_all_nodes
from tests._repo_check import load_check
from tests.conftest import TEST_PASSWORD
from tests.shop.helpers import make_shop_app

check = load_check()
MINE = {"channel.web", "pay.wechat", "pay.alipay", "pay.fake", "trigger.confirm_timeout", "channel.xhs", "channel.xianyu",
        "channel.douyin", "gate.platform_text"}
SHELLS = {"order.signal", "order.waiting_customer"}  # 订单中枢的薄壳（主窗口合并）


def test_cards_registered_and_runnable(settings, notifier, tmp_path):
    import_all_nodes()
    cards = {c.id: c for c in all_cards()}
    assert MINE | SHELLS <= set(cards)
    assert all(has_handler(i) for i in MINE | SHELLS if i != "channel.douyin") and not has_handler("channel.douyin")
    assert {cards[i].owner for i in MINE} == {"B", "C"}
    app = make_shop_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        listed = c.get("/api/admin/nodes").json()
        ids = {n["id"] for n in (listed if isinstance(listed, list) else listed.get("nodes", listed.get("cards", [])))}
        assert MINE <= ids


def _write(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def test_check_rule11_skips_node_card_text(tmp_path):
    _write(tmp_path, "backend/app/platforms/redline.py", 'TIERS = {"all": ("微信",), "platform": ("小红书",)}\nPATTERNS = {}\n')
    _write(tmp_path, "backend/app/platforms/nodes/channel_x.py",
           'CARD = NodeCard(id="channel.x", name="小红书", description="查有没有微信号")\nregister(CARD)\n')
    assert check.check_platform_texts(tmp_path) == []
    _write(tmp_path, "backend/app/platforms/nodes/channel_x.py", 'TEXT = "加微信"\nCARD = NodeCard(name="小红书")\n')
    assert [p.what for p in check.check_platform_texts(tmp_path)] == ["发给平台买家的字里有「微信」"]


def test_check_rule15_fails_on_public_refund_and_missing_tests(tmp_path):
    _write(tmp_path, "backend/app/shop/router.py", '@router.post("/refunds")\ndef r(): ...\n')
    problems = check.check_shop_rules(tmp_path)
    assert any("退款" in p.what for p in problems)
    assert sum("没有测试" in p.what for p in problems) == len(check.SHOP_REQUIRED_TESTS)
    for p in problems:
        assert p.why and p.fix and p.see  # 失败信息三件：错在哪、怎么改、看哪份说明


def test_check_rule15_passes_on_this_repo():
    root = Path(__file__).resolve().parents[3]
    assert check.check_shop_rules(root) == []
