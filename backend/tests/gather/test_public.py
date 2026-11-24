"""对外接口：站点地图、来源记账、限频、不出路径；公众号回复不许带转发的说法。"""

from __future__ import annotations

import json

from app.gather.models import FunnelVisit
from tests.gather.conftest import login, make_gclient, release, set_config, start, upload, visitor


def test_site_map_links_and_footer(gclient):
    s = gclient.get("/api/gather/site").json()
    hrefs = {i["label"]: i["href"] for g in s["groups"] for i in g["items"]}
    assert hrefs["价目"] == "https://www.example.org/price"  # 11-18 官网并进平台前端，不再是 .html
    assert hrefs["下单"] == "https://app.example.org/order?from=tuku_nav"
    assert hrefs["找图"] == "https://tuku.example.org/tuku" and hrefs["投图"] == "https://tuku.example.org/submit"
    assert s["company"] == "杭州竹涧云科技有限公司" and s["icp"].startswith("浙ICP备")
    assert s["plugin_name"] == "PsyEngine 图库插件" and s["cta"]["text"] == "做汇报 PPT 看这里"
    assert s["brands"]["ppt"]["href"] == "https://www.example.org/"


def test_funnel_dedupe_share_and_whitelist(gclient, settings):
    from app.core.db import Database

    v = visitor(20)
    u = start(gclient, v)
    gclient.post("/api/gather/visit", json={"visitor": visitor(21), "src": "xhs", "landing": "/"})
    gclient.post("/api/gather/visit", json={"visitor": visitor(21), "src": "xhs", "landing": "/search"})  # 30 分钟内不重记
    gclient.post("/api/gather/visit", json={"visitor": visitor(22), "src": "wechat", "landing": "/"})  # 白名单外 → other
    gclient.post("/api/gather/visit", json={"visitor": visitor(23), "share": u["share_code"], "landing": "/"})
    gclient.post("/api/gather/visit", json={"visitor": visitor(23), "share": u["share_code"], "landing": "/"})  # 同一人不重复加
    db = Database(settings.DATABASE_URL)
    with db.session() as s:
        rows = s.query(FunnelVisit).all()
        assert sorted(r.src for r in rows) == ["other", "share", "xhs"]
    db.dispose()
    st = gclient.get(f"/api/gather/unlock/{u['share_code']}", params={"visitor": v}).json()
    assert st["share_visits"] == 1


def test_cta_click_recorded_and_overview(gclient):
    assert gclient.post("/api/gather/cta", json={"placement": "unlock_done", "target": "order", "visitor": visitor(30)}).status_code == 204
    login(gclient)
    o = gclient.get("/api/admin/gather/overview").json()
    assert {"what": "unlock_done→order", "n": 1} in o["cta_clicks"]


def test_public_endpoints_rate_limited(settings, notifier):
    """对外接口限频：领取、交截图、开放接口超频回 429。"""
    with make_gclient(settings, notifier, GATHER_RATE_PER_HOUR=2, OPEN_API_RATE_PER_HOUR=1) as c:
        assert c.post("/api/gather/unlock", json={"visitor": visitor(40)}).status_code == 200
        assert c.post("/api/gather/unlock", json={"visitor": visitor(41)}).status_code == 200
        assert c.post("/api/gather/unlock", json={"visitor": visitor(42)}).status_code == 429
        c.get("/api/gather/open/v1/types")
        assert c.get("/api/gather/open/v1/types").status_code == 429
        assert c.post("/api/gather/unlock/XXXXXX/evidence", data={"visitor": visitor(40)},
                      files={"image": ("a.png", b"x", "image/png")}).status_code in (404, 429)


def test_no_paths_in_gather_public_responses(gclient):
    """截图、原图路径不出对外接口：真调一遍对外接口，返回里没有 storage 路径、本机路径、file / sha256 字段。"""
    release(gclient)
    v = visitor(50)
    bodies = [gclient.get("/api/gather/site").text]
    u = start(gclient, v)
    bodies.append(json.dumps(u, ensure_ascii=False))
    bodies.append(upload(gclient, u["share_code"], v, seed=50).text)
    bodies.append(gclient.get(f"/api/gather/unlock/{u['share_code']}", params={"visitor": v}).text)
    bodies.append(gclient.post(f"/api/gather/unlock/{u['share_code']}/resend", json={"visitor": v}).text)
    bodies.append(gclient.get("/api/gather/open/v1/types").text)
    bodies.append(gclient.get("/api/gather/open/v1/find", params={"q": "中介模型"}).text)
    bodies.append(gclient.get("/api/gather/open/v1/openapi.json").text)
    for b in bodies:
        assert "gather/evidence" not in b and "/Users/" not in b and "资料/" not in b
        assert '"file"' not in b and '"sha256"' not in b


def test_gzh_reply_rejects_forward_wording(gclient):
    login(gclient)
    r = gclient.put("/api/admin/gather/config", json={"gzh_reply_text": "转发到朋友圈就送：{url}"})
    assert r.status_code == 400 and "公众号回复里不能写" in r.json()["detail"]
    assert gclient.get("/api/admin/gather/gzh-reply").json()["missing"]
    release(gclient, tier="lite", url="https://pan.example.invalid/s/lite")
    t = gclient.get("/api/admin/gather/gzh-reply").json()
    assert "https://pan.example.invalid/s/lite" in t["text"] and "https://tuku.example.org" in t["text"]
    assert "转发" not in t["text"]


def test_unlock_off_switch(gclient):
    set_config(gclient, unlock_enabled=False)
    assert gclient.post("/api/gather/unlock", json={"visitor": visitor(60)}).status_code == 403
