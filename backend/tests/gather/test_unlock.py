"""领全量图库这条线（gather_figures 流程）：发起、交截图、核验、发链接、留痕、等链接自动补发、换核验方式。"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import func, select

from app.core.db import Database
from app.core.events import Event
from app.gather.models import FigureUnlock, PackGrant
from tests.gather.conftest import FAKE_PACK_URL, login, release, set_config, start, upload, visitor

FLOW_FILE = Path(__file__).resolve().parents[2] / "app" / "gather" / "flows" / "gather_figures.json"


def test_same_visitor_gets_same_share_code(gclient):
    a = start(gclient, visitor(1), "gzh")
    b = start(gclient, visitor(1))
    assert a["share_code"] == b["share_code"] and len(a["share_code"]) == 6
    assert "https://tuku.example.org/?s=" + a["share_code"] in a["share_text"]
    assert a["stage"] == "requested" and a["pack_text"] == ""


def test_unverified_never_gets_pack_link(gclient):
    """未核验不发全量链接：没交截图、等负责人看、截图被标假，返回里都没有网盘链接。"""
    release(gclient)
    v = visitor(2)
    u = start(gclient, v)
    assert FAKE_PACK_URL not in str(u)
    st = gclient.get(f"/api/gather/unlock/{u['share_code']}", params={"visitor": v}).json()
    assert st["pack_text"] == "" and FAKE_PACK_URL not in str(st)

    set_config(gclient, verifier="manual")  # 换成「负责人看过再发」：交了截图也只到「等负责人看」
    v2 = visitor(3)
    u2 = start(gclient, v2)
    r = upload(gclient, u2["share_code"], v2, seed=3).json()
    assert r["stage"] == "checking" and FAKE_PACK_URL not in str(r)

    # 截图被标假的人：之后都不给
    login(gclient)
    items = gclient.get("/api/admin/gather/unlocks").json()["items"]
    ev = next(i for i in items if i["share_code"] == u2["share_code"])["evidence"][0]
    gclient.post(f"/api/admin/gather/evidence/{ev['id']}/mark", json={"mark": "fake"})
    set_config(gclient, verifier="screenshot_trust")
    r = upload(gclient, u2["share_code"], v2, seed=4).json()
    assert r["stage"] in ("checking", "requested") and FAKE_PACK_URL not in str(r)
    # 别人拿分享码查不到
    assert gclient.get(f"/api/gather/unlock/{u2['share_code']}", params={"visitor": visitor(99)}).status_code == 404


def test_screenshot_trust_sends_link(gclient):
    release(gclient)
    v = visitor(4)
    u = start(gclient, v)
    r = upload(gclient, u["share_code"], v, seed=5).json()
    assert r["stage"] == "sent" and FAKE_PACK_URL in r["pack_text"] and "提取码 ab12" in r["pack_text"]
    assert "https://app.example.org/order?from=tuku_pack" in r["pack_text"]
    # 同一张图换个人交 → 再交一张
    v2 = visitor(5)
    u2 = start(gclient, v2)
    r2 = upload(gclient, u2["share_code"], v2, seed=5).json()
    assert r2["stage"] == "requested" and "之前交过" in r2["reason"] and r2["pack_text"] == ""


def test_pack_sent_is_logged(gclient, settings):
    """发链接留痕：发一次有一行发放 + 一个 figure.pack_sent 事件；重发只加次数。"""
    release(gclient)
    v = visitor(6)
    u = start(gclient, v)
    upload(gclient, u["share_code"], v, seed=6)
    r = gclient.post(f"/api/gather/unlock/{u['share_code']}/resend", json={"visitor": v}).json()
    assert r["stage"] == "sent" and FAKE_PACK_URL in r["pack_text"]
    db = Database(settings.DATABASE_URL)
    with db.session() as s:
        unlock = s.scalar(select(FigureUnlock).where(FigureUnlock.share_code == u["share_code"]))
        grants = s.scalars(select(PackGrant).where(PackGrant.unlock_id == unlock.id)).all()
        assert len(grants) == 1 and grants[0].resend_count == 1
        n = s.scalar(select(func.count()).select_from(Event).where(Event.type == "figure.pack_sent",
                                                                   Event.subject == f"figure_unlock:{unlock.id}"))
        assert n == 2
    db.dispose()


def test_no_pack_waits_then_auto_sends(gclient, notifier):
    v = visitor(7)
    u = start(gclient, v)
    r = upload(gclient, u["share_code"], v, seed=7).json()
    assert r["stage"] == "passed" and r["pack_text"] == ""
    assert any("网盘链接" in m for m in notifier.sent)
    out = release(gclient)
    assert out["resent"] == 1
    st = gclient.get(f"/api/gather/unlock/{u['share_code']}", params={"visitor": v}).json()
    assert st["stage"] == "sent" and FAKE_PACK_URL in st["pack_text"]


def test_admin_pass_from_review(gclient):
    release(gclient)
    set_config(gclient, verifier="manual")
    v = visitor(8)
    u = start(gclient, v)
    upload(gclient, u["share_code"], v, seed=8)
    login(gclient)
    item = next(i for i in gclient.get("/api/admin/gather/unlocks").json()["items"] if i["share_code"] == u["share_code"])
    assert [a["on"] for a in item["actions"]] == ["admin_pass", "admin_reject"]
    assert gclient.post(f"/api/admin/gather/unlocks/{item['id']}/push", json={"on": "resend"}).status_code == 409
    r = gclient.post(f"/api/admin/gather/unlocks/{item['id']}/push", json={"on": "admin_pass"}).json()
    assert r["stage"] == "sent"


def test_verifier_switch_without_flow_change(gclient):
    """核验方式改后台一项就换：screenshot_trust → share_visits（N=3），流程文件一个字不改。"""
    before = hashlib.sha256(FLOW_FILE.read_bytes()).hexdigest()
    release(gclient)
    set_config(gclient, verifier="share_visits", share_visits_n=3)
    v = visitor(9)
    u = start(gclient, v)
    assert u["need_visits"] == 3
    gclient.post("/api/gather/visit", json={"visitor": v, "share": u["share_code"], "landing": "/"})  # 自己点不算
    for i in range(3):
        gclient.post("/api/gather/visit", json={"visitor": visitor(100 + i), "share": u["share_code"], "landing": "/"})
        st = gclient.get(f"/api/gather/unlock/{u['share_code']}", params={"visitor": v}).json()
        assert st["share_visits"] == i + 1
    assert st["stage"] == "sent" and FAKE_PACK_URL in st["pack_text"]
    assert hashlib.sha256(FLOW_FILE.read_bytes()).hexdigest() == before


def test_follow_gzh_mode_points_to_gzh(gclient):
    release(gclient)
    set_config(gclient, verifier="follow_gzh")
    v = visitor(10)
    u = start(gclient, v)
    r = upload(gclient, u["share_code"], v, seed=10).json()
    assert r["stage"] == "requested" and "公众号 PsyEngine" in r["reason"] and r["pack_text"] == ""
    site = gclient.get("/api/gather/site").json()
    assert site["verifier"] == "follow_gzh" and "回复「图库」" in site["follow_note"]


def test_flow_loads_and_illegal_push_rejected(gclient):
    from app.intake import flow

    f = flow.load_flow("gather_figures")
    assert f.subject == "figure_unlock" and flow.check_nodes(f) == []
    v = visitor(11)
    u = start(gclient, v)
    login(gclient)
    item = next(i for i in gclient.get("/api/admin/gather/unlocks").json()["items"] if i["share_code"] == u["share_code"])
    assert gclient.post(f"/api/admin/gather/unlocks/{item['id']}/push", json={"on": "evidence"}).status_code == 409
