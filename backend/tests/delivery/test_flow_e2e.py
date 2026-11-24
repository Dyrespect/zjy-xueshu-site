"""最小闭环（顶层设计第十三节、设计第十一节第 3 条），全走接口、假模型、假工厂文件：

已付款 → 已认领 → 收资料 → 制作中 → 制作方交 6 页（进出图队列）→ 后台圈出图 → 已交水印版 → 交付页逐页标 2 处要改、提交
→ 修改中 → 再交 → 已交水印版 → 确认收货 → 已完成 → 已交付 → 下载 pptx 和讲稿。每一格有 intake.stage，本模块事件齐。
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.events import Event
from app.intake.models import Order
from app.intake.runtime import get_runtime
from tests.delivery.helpers import H, delivery_app, maker_files, run_queue
from tests.intake.helpers import ready


def test_minimal_loop_paid_to_delivered(settings, notifier, tmp_path):
    app = delivery_app(settings, notifier, tmp_path, DELIVERY_SYNC_MAX_PAGES=0)
    with TestClient(app) as c:
        rt = get_runtime(app)
        with rt.database.session() as db:
            _, o = ready(db, rt.ctx, name="闭环")  # 码池的码认领 → 资料齐 → 今天有名额 → 制作中（交接工厂）
            oid, token = o.id, o.delivery_token
            assert o.stage == "making"

        # 第 1 版：制作方交 6 页 → 队列 → 出图 → 发布
        r = c.post(f"/api/intake/production/orders/{oid}/package", headers=H, files=maker_files(6), data={"note": "第一版"})
        assert r.status_code == 200, r.text
        assert run_queue(app) == 1
        d = c.get(f"/api/delivery/{token}").json()
        assert d["status"] == "已交水印版" and len(d["rounds"][0]["pages"]) == 6
        for p in d["rounds"][0]["pages"][:2]:
            assert c.get(p["url"]).headers["content-type"] == "image/jpeg"
        c.post(f"/api/delivery/{token}/viewed", json={"round": 1, "pages": 6})
        bad = c.get(f"/api/delivery/{token}/final/1")
        assert bad.status_code in (403, 404)

        # 交付页逐页标 2 处要改
        items = [{"page": 2, "text": "时间轴太挤，挪一个点到下一行"}, {"page": 5, "text": "图 3 换成原文的 Figure 2"}]
        r = c.post(f"/api/delivery/{token}/revision", data={"items": json.dumps(items, ensure_ascii=False), "based_on_round": "1"})
        assert r.status_code == 200, r.text
        assert c.get(f"/api/delivery/{token}").json()["status"] == "修改中"
        msgs = c.get("/api/intake/production/messages", headers=H).json()
        brief = next(m for m in msgs if m["kind"] == "改稿单")["text"]
        assert "第 2 页" in brief and "第 5 页" in brief and "第 1 版 → 第 2 版" in brief

        # 第 2 版
        r = c.post(f"/api/intake/production/orders/{oid}/package", headers=H, files=maker_files(6), data={"note": "按改稿单改好"})
        assert r.status_code == 200, r.text
        assert run_queue(app) == 1
        d = c.get(f"/api/delivery/{token}").json()
        assert d["status"] == "已交水印版" and [x["round"] for x in d["rounds"]] == [1, 2] and d["receipt"]["mode"] == "button"

        # 确认收货 → 已完成 → 已交付 → 下载
        r = c.post(f"/api/delivery/{token}/received").json()
        assert r["released"] and [f["kind"] for f in r["files"]] == ["PPT", "讲稿"]
        for f in r["files"]:
            got = c.get(f["url"])
            assert got.status_code == 200 and got.content

        with rt.database.session() as db:
            o = db.get(Order, oid)
            assert o.stage == "delivered" and o.delivery_round == 2 and o.completed_at and o.finished_at
            hops = [e.content for e in db.scalars(select(Event).where(Event.type == "intake.stage", Event.subject == f"order:{oid}")
                                                  .order_by(Event.id))]
            steps = [h["to_step"] for h in hops]
            for seq in (["making", "proofing"], ["proofing", "publish", "watermarked"], ["watermarked", "revising", "proofing"],
                        ["confirm", "completed", "delivered"]):
                assert any(steps[i:i + len(seq)] == seq for i in range(len(steps))), (seq, steps)
            types = [e.type for e in db.scalars(select(Event).where(Event.subject == f"order:{oid}", Event.type.like("delivery.%")))]
            for t, n in (("delivery.package_received", 2), ("delivery.watermarked", 2), ("delivery.proof_published", 2),
                         ("delivery.version_published", 2), ("delivery.revision", 1), ("delivery.receipt_clicked", 1),
                         ("delivery.proof_viewed", 1), ("delivery.final_downloaded", 2)):
                assert types.count(t) == n, (t, types.count(t))
