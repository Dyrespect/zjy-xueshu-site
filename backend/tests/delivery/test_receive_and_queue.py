"""收成品包（deliver.receive：E2、E3、必交讲稿、文件坏、版本表）和出图队列（deliver.watermark 排队 → 后台圈出图 → 发布）。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.nodes import NodeCall, run_node
from app.delivery import runtime, versions
from app.delivery.checks import verify_proof
from app.delivery.models import DeliveryVersion
from app.intake.models import Order, Outbox
from app.intake.runtime import get_runtime
from tests.delivery.helpers import H, add_package, delivery_app, dsettings, maker_files, run_queue
from tests.intake.helpers import ready


def _receive(db, ctx, o, **kw):
    return run_node("deliver.receive", NodeCall(db, ctx, "maker", o.id), {"order_id": o.id, **kw})


def _making(db, ctx, name="收包"):
    _, o = ready(db, ctx, name=name)
    assert o.stage == "making"
    return o


@pytest.mark.parametrize("kw,words", [
    (dict(pages=2, page_size=(1334, 750)), ["第 1 页长边 1334", "缩略图", "deliver_pages.py"]),
    (dict(pages=2, slides=3), ["pptx 3 页", "整页图只有 2 张", "缺第 3 页"]),
    (dict(pages=2, slides=5), ["缺第 3–5 页"]),
    (dict(pages=3, skip=(2,)), ["页码不连续", "缺第 2 页"]),
    (dict(pages=2, script=False), ["缺讲稿"]),
])
def test_bad_packages_rejected_with_three_parts(database, ctx, kw, words):
    with database.session() as db:
        o = _making(db, ctx)
        add_package(db, ctx, o, **kw)
        res = _receive(db, ctx, o)
        assert res.exit == "fail"
        for w in words:
            assert w in res.detail, res.detail
        assert "怎么改" in res.detail and "说明" in res.detail
        assert o.stage == "making" and versions.version_of(db, o.id, 1) is None


def test_broken_pptx_and_hidden_slides(database, ctx):
    from app.intake import service
    from app.intake.models import PAGE_KIND
    from tests.delivery.helpers import slide_png
    from tests.intake.helpers import pptx_bytes

    with database.session() as db:
        o = _making(db, ctx)
        service.add_deliverable(db, ctx, o, filename="deck.pptx", data=b"PK\x03\x04broken", kind="PPT")
        service.add_deliverable(db, ctx, o, filename="讲稿.docx", data=b"x", kind="讲稿")
        res = _receive(db, ctx, o)
        assert res.exit == "fail" and "打不开" in res.detail
        # 隐藏页不算（PowerPoint 导出 PDF 不导隐藏页）：3 张里 1 张隐藏 + 2 张整页图 = 对得上；重传以最后一次为准
        service.add_deliverable(db, ctx, o, filename="deck.pptx", data=pptx_bytes(2, hidden=1), kind="PPT")
        for i in (1, 2):
            service.add_deliverable(db, ctx, o, filename=f"p{i}.png", data=slide_png(i), kind=PAGE_KIND, page_no=i)
        res = _receive(db, ctx, o, note="第一版")
        assert res.exit == "ok", res.detail
        assert res.output.slide_count == 2 and res.output.page_count == 2


def test_accepted_package_records_version_and_publishes(database, ctx):
    with database.session() as db:
        o = _making(db, ctx)
        add_package(db, ctx, o, pages=3)
        res = _receive(db, ctx, o, note="第一版", source="admin_upload")
        assert res.exit == "ok" and res.output.round == 1
        assert o.stage == "watermarked" and o.delivery_round == 1  # 3 页 ≤ 4：当场出图 → 发布
        v = versions.version_of(db, o.id, 1)
        assert v.status == "published" and v.source == "admin_upload" and v.page_count == 3 and len(v.page_sha256) == 3
        assert len(v.proof_file_ids) == 3 and v.watermark_spec["alpha"] == 0.20 and v.watermark_spec["warp"] is True
        assert v.published_at is not None and v.rendered_at is not None
        assert [p.page for p in versions.proof_rounds(db, o)[0].pages] == [1, 2, 3]


def test_queue_renders_in_background_then_publishes_link_only(settings, notifier, tmp_path):
    app = delivery_app(settings, notifier, tmp_path, DELIVERY_SYNC_MAX_PAGES=0)
    with TestClient(app) as c:
        rt = get_runtime(app)
        with rt.database.session() as db:
            _, o = ready(db, rt.ctx, name="排队")
            oid, token = o.id, o.delivery_token
        r = c.post(f"/api/intake/production/orders/{oid}/package", headers=H, files=maker_files(5), data={"note": "第一版"})
        assert r.status_code == 200, r.text
        assert r.json()["stage_label"] == "制作中"  # 进了出图队列，接口马上返回
        with rt.database.session() as db:
            o = db.get(Order, oid)
            v = versions.version_of(db, oid, 1)
            assert o.flow_step == "proofing" and v.status == "rendering" and v.page_count == 5
        assert c.get(f"/api/delivery/{token}").json()["rounds"] == []
        assert run_queue(app) == 1
        with rt.database.session() as db:
            o = db.get(Order, oid)
            v = versions.version_of(db, oid, 1)
            assert o.stage == "watermarked" and v.status == "published"
            obs = list(db.scalars(select(Outbox).where(Outbox.order_id == oid, Outbox.category == "交付")))
            assert [ob.kind for ob in obs] == ["text"] and "/d/" in obs[0].text  # E6：水印阶段只发链接，不发文件
        d = c.get(f"/api/delivery/{token}").json()
        assert len(d["rounds"][0]["pages"]) == 5
        for p in d["rounds"][0]["pages"]:
            img = c.get(p["url"])
            assert img.headers["content-type"] == "image/jpeg"
            verify_proof(img.content)
        assert run_queue(app) == 0  # 出过的不再出


def test_queue_failure_retries_then_notifies_and_admin_rerender(settings, notifier, tmp_path):
    from tests.conftest import TEST_PASSWORD

    app = delivery_app(settings, notifier, tmp_path, DELIVERY_SYNC_MAX_PAGES=0, DELIVERY_RENDER_MAX_ATTEMPTS=2)
    with TestClient(app) as c:
        rt = get_runtime(app)
        with rt.database.session() as db:
            o = _making(db, rt.ctx, name="出图坏了")
            add_package(db, rt.ctx, o, pages=2)
            assert _receive(db, rt.ctx, o).exit == "ok"
            v = versions.version_of(db, o.id, 1)
            oid, vid = o.id, v.id
            from app.intake.models import FileRecord

            page = db.get(FileRecord, v.page_file_ids[0])
            rt.ctx.storage.local_path(page.storage_key).write_bytes(b"not an image")  # 底图坏了
        run_queue(app)
        with rt.database.session() as db:
            v = db.get(DeliveryVersion, vid)
            assert v.status == "rendering" and v.attempts == 1 and v.error
        run_queue(app)
        with rt.database.session() as db:
            v = db.get(DeliveryVersion, vid)
            assert v.status == "failed" and v.attempts == 2 and db.get(Order, oid).flow_step == "proofing"
        assert any("出水印图失败" in m for m in notifier.sent)
        c.post("/api/auth/login", json={"password": TEST_PASSWORD})
        d = c.get(f"/api/admin/delivery/orders/{oid}/versions").json()
        assert d["versions"][0]["status_label"] == "出图失败" and d["watermark_alpha"] == 0.20
        assert c.post(f"/api/admin/delivery/versions/{vid}/rerender").json()["status"] == "rendering"


def test_reupload_during_proofing_uses_latest_pages(database, ctx):
    runtime.configure(dsettings(DELIVERY_SYNC_MAX_PAGES=0))
    with database.session() as db:
        o = _making(db, ctx, name="重传")
        add_package(db, ctx, o, pages=2)
        assert _receive(db, ctx, o).exit == "ok" and o.flow_step == "proofing"
        first = list(versions.version_of(db, o.id, 1).page_file_ids)
        add_package(db, ctx, o, pages=2)  # 发现传错了，整版重传
        assert _receive(db, ctx, o).exit == "ok" and o.flow_step == "proofing"
        v = versions.version_of(db, o.id, 1)
        assert v.status == "rendering" and set(v.page_file_ids).isdisjoint(first)
        assert len(db.scalars(select(DeliveryVersion).where(DeliveryVersion.order_id == o.id)).all()) == 1
