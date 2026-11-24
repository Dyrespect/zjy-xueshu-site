"""交付页接口：令牌、noindex、交水印版前什么都拿不到；逐页水印图；最终版只在已完成之后（E5）；水印阶段聊天里不发文件（E6）；
逐页提修改的合法性（E9）；确认收货按渠道（自有渠道按钮、平台单去平台点）；看了几页记下来；反馈。"""

from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.events import Event
from app.core.nodes import NodeCall, run_node
from app.delivery.checks import verify_proof
from app.intake import clock, flow, service
from app.intake.models import Order, Outbox
from app.intake.runtime import get_runtime
from tests.delivery.helpers import add_package, delivery_app
from tests.intake.helpers import PDF_BYTES, ready


def _deliver(rt, oid, pages=3):
    with rt.database.session() as db:
        o = db.get(Order, oid)
        add_package(db, rt.ctx, o, pages=pages)
        res = run_node("deliver.receive", NodeCall(db, rt.ctx, "maker", o.id), {"order_id": o.id})
        assert res.exit == "ok", res.detail


@pytest.fixture
def env(settings, notifier, tmp_path):
    app = delivery_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        rt = get_runtime(app)
        with rt.database.session() as db:
            _, o = ready(db, rt.ctx, name="Carrie", sku="light-p1", minutes=12)
            service.update_order(db, rt.ctx, o, {"title": "CFPS 数据里的代际流动"})
            token, oid = o.delivery_token, o.id
        yield app, c, rt, token, oid


def test_before_delivery_nothing_to_get(env):
    app, c, rt, token, oid = env
    r = c.get(f"/api/delivery/{token}")
    assert r.status_code == 200 and "noindex" in r.headers["x-robots-tag"]
    d = r.json()
    assert d["title"] == "CFPS 数据里的代际流动" and d["order_no"] == f"{oid:05d}"
    assert d["status"] == "制作中" and d["step"] == 1 and d["rounds"] == [] and not d["delivered"]
    assert "预计" in d["due_text"] and "前交第一版" in d["due_text"]
    assert d["receipt"]["mode"] == "none" and not d["final"]["released"] and d["final"]["files"] == []
    assert c.post(f"/api/delivery/{token}/revision", data={"text": "改一下"}).status_code == 400
    assert c.post(f"/api/delivery/{token}/received").status_code == 400
    assert c.get(f"/api/delivery/{token}/proofs/1/1").status_code == 404
    assert c.get("/api/delivery/abc").status_code == 404


def test_proofs_page_by_page_only_watermarked_jpeg(env):
    app, c, rt, token, oid = env
    _deliver(rt, oid, pages=3)
    d = c.get(f"/api/delivery/{token}").json()
    assert d["status"] == "已交水印版" and d["step"] == 2 and d["latest_round"] == 1
    assert [p["page"] for p in d["rounds"][0]["pages"]] == [1, 2, 3]
    assert "storage" not in json.dumps(d) and "files" not in d  # 不给路径、不给打包下载
    img = c.get(d["rounds"][0]["pages"][1]["url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/jpeg" and "inline" in img.headers["content-disposition"]
    assert verify_proof(img.content).width == 1920
    assert c.get(f"/api/delivery/{token}/proofs/1/9").status_code == 404
    assert d["receipt"]["mode"] == "button" and "自动确认收货" in d["receipt"]["auto_confirm_text"]
    assert d["revision"]["can_submit"] and d["revision"]["page_count"] == 3 and d["revision"]["whole_items_max"] == 3
    with rt.database.session() as db:  # E6：水印阶段聊天里只发链接
        kinds = [ob.kind for ob in db.scalars(select(Outbox).where(Outbox.order_id == oid, Outbox.category == "交付"))]
        assert kinds == ["text"]


@pytest.mark.parametrize("step", ["claimed", "collecting", "making", "proofing", "publish", "watermarked", "revising", "void"])
def test_e5_final_only_after_completed(env, step):
    app, c, rt, token, oid = env
    _deliver(rt, oid, pages=2)
    with rt.database.session() as db:
        o = db.get(Order, oid)
        ppt = next(f for f in service.round_files(db, o, 1) if f.purpose == "PPT")
        flow.seed_stage(o, step)
        fid = ppt.id
    r = c.get(f"/api/delivery/{token}/final/{fid}")
    assert r.status_code == 403 and "确认收货后才能下载" in r.json()["detail"], f"「{step}」时下载到了 deck.pptx → 下载只走关口 → 设计 4.6 节"
    with rt.database.session() as db:
        res = run_node("gate.final", NodeCall(db, rt.ctx, "test", oid), {"order_id": oid})
        assert res.exit == "fail"
    assert c.get(f"/api/delivery/{token}").json()["final"]["files"] == []


def test_e9_revision_per_page_validation_and_brief(env):
    app, c, rt, token, oid = env
    _deliver(rt, oid, pages=3)
    bad = c.post(f"/api/delivery/{token}/revision", data={"items": json.dumps([{"page": 9, "text": "换个图"}])})
    assert bad.status_code == 409 and "第 9 页不存在（共 3 页）" in bad.json()["detail"] and "怎么改" in bad.json()["detail"]
    many = [{"page": None, "text": f"整体意见 {i}"} for i in range(4)]
    assert "整体意见写了 4 条" in c.post(f"/api/delivery/{token}/revision", data={"items": json.dumps(many)}).json()["detail"]
    stale = c.post(f"/api/delivery/{token}/revision", data={"items": json.dumps([{"page": 1, "text": "标题大一号"}]), "based_on_round": 0})
    assert stale.status_code == 409 and "最新一版" in stale.json()["detail"]
    assert c.post(f"/api/delivery/{token}/revision", data={"items": "[]"}).status_code == 409

    items = [{"page": 2, "text": "时间轴太挤，1971—1972 挪到下一行", "files": [0]}, {"page": 1, "text": "标题字再大一号"},
             {"page": None, "text": "配色深一点"}]
    form = {"items": json.dumps(items, ensure_ascii=False), "based_on_round": "1"}
    r = c.post(f"/api/delivery/{token}/revision", data=form, files=[("files", ("圈改.png", PDF_BYTES, "image/png"))])
    assert r.status_code == 200, r.text
    assert r.json()["free"] and "小时内交下一版" in r.json()["message"]
    again = c.post(f"/api/delivery/{token}/revision", data=form, files=[("files", ("圈改.png", PDF_BYTES, "image/png"))])
    assert again.status_code == 200 and "已经提交过了" in again.json()["message"]  # 重复点提交：不重复扣轮数
    other = c.post(f"/api/delivery/{token}/revision", data={"items": json.dumps([{"page": 3, "text": "再改一处"}])})
    assert other.status_code == 409 and "上一轮修改还没改完" in other.json()["detail"]
    d = c.get(f"/api/delivery/{token}").json()
    assert d["status"] == "修改中" and d["revision"]["open"] and not d["revision"]["can_submit"] and d["revision"]["revision_used"] == 1
    msgs = c.get("/api/intake/production/messages", headers={"Authorization": "Bearer maker-token-for-tests"}).json()
    brief = next(m for m in msgs if m["kind"] == "改稿单")["text"]
    assert brief.index("第 1 页") < brief.index("第 2 页") < brief.index("整体")  # 按页排
    assert "（附件：圈改.png）" in brief and "页码 = 水印版底栏" in brief


def test_confirm_releases_finals_on_same_page(env):
    app, c, rt, token, oid = env
    _deliver(rt, oid, pages=2)
    r = c.post(f"/api/delivery/{token}/received")
    assert r.status_code == 200 and r.json()["released"]
    assert [f["kind"] for f in r.json()["files"]] == ["PPT", "讲稿"]
    d = c.get(f"/api/delivery/{token}").json()
    assert d["status"] == "已交付" and d["step"] == 4 and d["final"]["released"] and d["rounds"] == []  # 放出后不再列水印版
    ppt = d["final"]["files"][0]
    got = c.get(ppt["url"])
    assert got.status_code == 200 and got.content[:2] == b"PK" and "attachment" in got.headers["content-disposition"]
    assert c.get(f"/api/delivery/{token}/proofs/1/1").status_code == 404
    assert c.get(f"/api/delivery/{token}/final/99999").status_code == 404
    with rt.database.session() as db:
        types = {e.type for e in db.scalars(select(Event).where(Event.subject == f"order:{oid}"))}
        assert {"delivery.receipt_clicked", "intake.order_completed", "intake.final_released", "delivery.final_downloaded"} <= types
        kinds = sorted(ob.kind for ob in db.scalars(select(Outbox).where(Outbox.order_id == oid, Outbox.category == "交付")))
        assert kinds == ["file", "file", "text", "text"]  # 放出之后才发文件（E6）
    again = c.post(f"/api/delivery/{token}/received")  # 再点一次：幂等，照样给最终版，不重复发
    assert again.status_code == 200 and again.json()["released"]
    with rt.database.session() as db:
        assert db.scalar(select(func.count()).select_from(Outbox).where(Outbox.order_id == oid, Outbox.category == "交付")) == 4


def test_platform_order_goes_to_platform_and_claim_notifies_once(settings, notifier, tmp_path):
    app = delivery_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        rt = get_runtime(app)
        with rt.database.session() as db:
            _, o = ready(db, rt.ctx, name="闲鱼客人", platform="xy")
            oid, token = o.id, o.delivery_token
        _deliver(rt, oid, pages=2)
        d = c.get(f"/api/delivery/{token}").json()
        assert d["receipt"]["mode"] == "platform" and d["receipt"]["platform_name"] == "闲鱼" and "闲鱼" in d["receipt"]["hint"]
        r = c.post(f"/api/delivery/{token}/received")
        assert r.status_code == 409 and "平台" in r.json()["detail"]
        n = len(notifier.sent)
        assert "核对" in c.post(f"/api/delivery/{token}/platform-confirmed").json()["message"]
        c.post(f"/api/delivery/{token}/platform-confirmed")
        assert len([m for m in notifier.sent[n:] if "点了确认收货" in m]) == 1  # 6 小时内只通知一次
        with rt.database.session() as db:
            assert db.get(Order, oid).stage == "watermarked"  # 客人说的不算，订单不动


def test_viewed_once_per_round_per_day_and_feedback(env):
    app, c, rt, token, oid = env
    _deliver(rt, oid, pages=2)
    for _ in range(3):
        assert c.post(f"/api/delivery/{token}/viewed", json={"round": 1, "pages": 2}).json()["ok"]
    with rt.database.session() as db:
        rows = list(db.scalars(select(Event).where(Event.type == "delivery.proof_viewed", Event.subject == f"order:{oid}")))
        assert len(rows) == 1 and rows[0].content["pages"] == 2
    assert c.get(f"/api/delivery/{token}").json()["show_feedback"] is False
    with rt.database.session() as db:
        db.get(Order, oid).present_date = clock.today()
    assert c.get(f"/api/delivery/{token}").json()["show_feedback"] is True
    r = c.post(f"/api/delivery/{token}/feedback", json={"satisfaction": "满意", "comment": "老师说图很清楚", "share_revised": True})
    assert r.json()["ok"] and c.get(f"/api/delivery/{token}").json()["feedback_done"]


def test_revisions_used_up_says_buy_more(env):
    app, c, rt, token, oid = env
    _deliver(rt, oid, pages=2)
    c.post(f"/api/delivery/{token}/revision", data={"items": json.dumps([{"page": 1, "text": "标题大一号"}])})
    _deliver(rt, oid, pages=2)  # 改好的第 2 版
    d = c.get(f"/api/delivery/{token}").json()
    assert d["status"] == "已交水印版" and [r["round"] for r in d["rounds"]] == [1, 2]
    assert not d["revision"]["can_submit"] and "再改一轮" in d["revision"]["hint"]
