"""反馈、提需求、投图、意见：入库、蜜罐、限流、上传检查；后台能看到、能标处理了。"""

from sqlalchemy import func, select

from app.core.db import Database
from app.core.events import Event
from app.figures.models import FigureFeedback, FigureRequest, FigureSubmission, SiteFeedback
from tests.conftest import TEST_PASSWORD
from tests.figures.conftest import first_id_of, make_client, needs_engine, tiny_png

pytestmark = needs_engine


def _count(settings, model) -> int:
    db = Database(settings.DATABASE_URL)
    with db.session() as s:
        n = s.scalar(select(func.count()).select_from(model))
    db.dispose()
    return n


def test_figure_feedback_saved_with_search(fclient, settings, engine):
    fid = first_id_of(engine, "D2")
    r = fclient.post(
        f"/api/figures/{fid}/feedback",
        json={"reason": "irrelevant", "note": "我搜的是眼动，这张是脑电", "query": "眼动实验流程", "search_id": 3},
    )
    assert r.status_code == 200
    assert "收到了" in r.json()["message"]
    db = Database(settings.DATABASE_URL)
    with db.session() as s:
        row = s.scalars(select(FigureFeedback)).one()
        assert (row.figure_id, row.reason, row.query, row.search_id, row.status) == (fid, "irrelevant", "眼动实验流程", 3, "new")
        assert s.scalars(select(Event).where(Event.type == "figures.feedback")).one().subject == f"figure:{fid}"
    db.dispose()
    assert fclient.post(f"/api/figures/{fid}/feedback", json={"reason": "乱写"}).status_code == 400
    assert fclient.post("/api/figures/99999999/feedback", json={"reason": "other"}).status_code == 404


def test_request_with_sketch(fclient, settings):
    r = fclient.post(
        "/api/figures/requests",
        data={"want": "fNIRS 光极排布图", "method": "近红外", "contact": "wx: psy_lin", "query": "功能性近红外 fNIRS 的光极排布图"},
        files={"sketch": ("草图.png", tiny_png(), "image/png")},
    )
    assert r.status_code == 200
    assert r.json()["message"] == "收到了。找到合适的图会通过你留的联系方式告诉你。"
    db = Database(settings.DATABASE_URL)
    with db.session() as s:
        row = s.scalars(select(FigureRequest)).one()
        assert row.want == "fNIRS 光极排布图" and row.contact == "wx: psy_lin"
        assert row.sketch.startswith("figures/requests/") and row.sketch.endswith(".png")
    db.dispose()


def test_request_rejects_bad_upload(fclient):
    r = fclient.post("/api/figures/requests", data={"want": "x 图"}, files={"sketch": ("a.png", b"not an image", "image/png")})
    assert r.status_code == 400 and "只收图片" in r.json()["detail"]
    big = b"\x89PNG" + b"0" * (5 * 1024 * 1024 + 10)
    r = fclient.post("/api/figures/requests", data={"want": "x 图"}, files={"sketch": ("a.png", big, "image/png")})
    assert r.status_code == 413
    assert fclient.post("/api/figures/requests", data={"want": ""}).status_code == 422


def test_submission_needs_image_and_source(fclient, settings):
    assert fclient.post("/api/figures/submissions", data={"source": "10.1037/abc"}).status_code == 400
    r = fclient.post(
        "/api/figures/submissions",
        data={"source": "10.1037/apl0000494", "reason": "分块清楚", "credit": "林同学"},
        files={"image": ("fig.png", tiny_png(), "image/png")},
    )
    assert r.status_code == 200 and "由 林同学 推荐" in r.json()["message"]
    assert _count(settings, FigureSubmission) == 1


def test_site_feedback(fclient, settings):
    r = fclient.post("/api/figures/site-feedback", json={"content": "希望能按年份筛", "contact": "", "page": "/search"})
    assert r.status_code == 200 and r.json()["message"] == "收到了，谢谢你的意见。"
    assert _count(settings, SiteFeedback) == 1


def test_honeypot_not_saved(fclient, settings, engine):
    fid = first_id_of(engine, "W2")
    assert fclient.post(f"/api/figures/{fid}/feedback", json={"reason": "other", "website": "http://spam"}).status_code == 200
    assert fclient.post("/api/figures/site-feedback", json={"content": "buy now", "website": "x"}).status_code == 200
    assert fclient.post("/api/figures/requests", data={"want": "spam", "website": "x"}).status_code == 200
    assert _count(settings, FigureFeedback) == 0
    assert _count(settings, SiteFeedback) == 0
    assert _count(settings, FigureRequest) == 0


def test_rate_limit_per_ip_kind_hour(settings, notifier, engine):
    fid = first_id_of(engine, "W2")
    with make_client(settings, notifier, FIGURE_RATE_LIMIT_PER_HOUR=3) as c:
        for _ in range(3):
            assert c.post(f"/api/figures/{fid}/feedback", json={"reason": "other"}).status_code == 200
        r = c.post(f"/api/figures/{fid}/feedback", json={"reason": "other"})
        assert r.status_code == 429 and "过一小时" in r.json()["detail"]
        # 别的类不受影响
        assert c.post("/api/figures/site-feedback", json={"content": "能加英文吗"}).status_code == 200


def test_admin_sees_and_handles(fclient, engine):
    fid = first_id_of(engine, "D2")
    fclient.post(f"/api/figures/{fid}/feedback", json={"reason": "wrong_type", "note": "这是实验设计图"})
    fclient.post("/api/figures/requests", data={"want": "眼动热区图", "query": "眼动"}, files={"sketch": ("s.png", tiny_png(), "image/png")})

    assert fclient.get("/api/admin/figures/inbox/feedback").status_code == 401
    assert fclient.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200

    fb = fclient.get("/api/admin/figures/inbox/feedback").json()
    assert fb["counts"] == {"new": 1, "done": 0}
    item = fb["items"][0]
    assert item["reason"] == "图型不对" and item["note"] == "这是实验设计图"
    assert item["figure"]["id"] == fid and item["figure"]["thumb_url"] == f"/api/figures/{fid}/thumb"

    rq = fclient.get("/api/admin/figures/inbox/requests").json()["items"][0]
    assert rq["want"] == "眼动热区图" and rq["image_url"]
    img = fclient.get(rq["image_url"])
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"

    r = fclient.patch(f"/api/admin/figures/inbox/feedback/{item['id']}", json={"status": "done", "admin_note": "改成 D1"})
    assert r.json()["status"] == "done" and r.json()["admin_note"] == "改成 D1" and r.json()["handled_at"]
    assert fclient.get("/api/admin/figures/inbox/feedback", params={"status": "new"}).json()["items"] == []
    assert fclient.patch("/api/admin/figures/inbox/feedback/999", json={"status": "done"}).status_code == 404


def test_admin_stats(fclient, engine):
    fclient.get("/api/figures/search", params={"q": "催眠诱导的流程"})
    body = fclient.get("/api/figures/search", params={"q": "技术路线"}).json()
    card = body["groups"][0]["cards"][0]
    fclient.post("/api/figures/clicks", json={"search_id": body["search_id"], "figure_id": card["id"]})
    fclient.post("/api/auth/login", json={"password": TEST_PASSWORD})
    st = fclient.get("/api/admin/figures/stats").json()
    assert st["today"] == 2 and st["week"] == 2
    assert st["zero_words"] == [{"word": "催眠诱导", "n": 1}]
    assert st["top_clicked"][0]["id"] == card["id"] and st["top_clicked"][0]["n"] == 1
    assert st["recent"][0]["query"] == "技术路线"
