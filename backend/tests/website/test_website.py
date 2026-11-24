"""官网：设置（页脚、联系电话、公安备案号）、robots.txt 跟着「公开给搜索引擎」开关走、下单前同意留痕。
（sitemap.xml 是前端构建时生成的，查它在 scripts/site_links.py。）"""

from __future__ import annotations

from sqlalchemy import select

from app.core.events import Event
from app.core.nodes import get_card
from app.website.consent import REQUIRED_CONSENTS
from tests.conftest import TEST_PASSWORD

ALL_ITEMS = list(REQUIRED_CONSENTS)


def _login(client):
    assert client.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200


def test_public_config_defaults(client):
    c = client.get("/api/website/config").json()
    assert c["company_name"] == "杭州竹涧云科技有限公司"
    assert c["credit_code"] == "91330110MAKFUNHCXY"
    assert c["icp"].startswith("浙ICP备")
    assert c["phone"] == "15068998671" and c["phone_note"] == "微信同号"
    assert c["police_beian"] == "" and c["police_beian_url"] == ""  # 没填不显示
    assert c["indexable"] is False and c["maintenance"] is False


def test_admin_settings_need_login_and_validate(client):
    assert client.get("/api/admin/website/settings").status_code == 401
    _login(client)
    s = client.get("/api/admin/website/settings").json()
    assert set(s["pending_launch"]) == {"police_beian", "email", "service_hours"}
    r = client.put("/api/admin/website/settings", json={"config": {"phone": "打电话给我"}})
    assert r.status_code == 422 and "电话" in r.json()["detail"]
    r = client.put("/api/admin/website/settings", json={"config": {"police_beian": "浙公网安备33010002000001号", "phone": "13800000000"}})
    assert r.status_code == 200 and "police_beian" not in r.json()["pending_launch"]
    c = client.get("/api/website/config").json()
    assert c["phone"] == "13800000000"
    assert c["police_beian_url"].endswith("code=33010002000001")


def test_robots_follow_index_switch(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/plain")
    assert "Disallow: /\n" in r.text and "Sitemap" not in r.text
    _login(client)
    client.put("/api/admin/website/settings", json={"config": {"indexable": True}})
    t = client.get("/robots.txt").text
    assert "Allow: /" in t and "Disallow: /admin" in t and "Disallow: /d/" in t and "Disallow: /order/pay/" in t
    assert "Sitemap: http://127.0.0.1:8710/sitemap.xml" in t
    assert "Disallow: /\n" not in t


def test_consent_requires_all_items(client, database):
    body = {"checkout_token": "tok_abcdef123", "items": ["terms_privacy"], "terms_version": "2026-11-18", "privacy_version": "2026-11-18"}
    r = client.post("/api/website/consent", json=body)
    assert r.status_code == 422 and "AI" in r.json()["detail"]
    r = client.post("/api/website/consent", json={**body, "items": ALL_ITEMS})
    assert r.status_code == 200
    with database.session() as db:
        ev = db.scalars(select(Event).where(Event.type == "website.consent")).one()
    assert ev.subject == "checkout:tok_abcdef123"
    assert sorted(ev.content["items"]) == sorted(ALL_ITEMS)
    assert ev.content["privacy_version"] == "2026-11-18" and ev.content["ip"]


def test_consent_rejects_bad_input(client):
    ok = {"checkout_token": "tok_abcdef123", "items": ALL_ITEMS, "terms_version": "2026-11-18", "privacy_version": "2026-11-18"}
    assert client.post("/api/website/consent", json={**ok, "checkout_token": "../../etc"}).status_code == 422
    assert client.post("/api/website/consent", json={**ok, "terms_version": "最新"}).status_code == 422


def test_admin_sees_consents(client):
    ok = {"checkout_token": "tok_seen_0001", "items": ALL_ITEMS, "terms_version": "2026-11-18", "privacy_version": "2026-11-18"}
    client.post("/api/website/consent", json=ok)
    _login(client)
    rows = client.get("/api/admin/website/consents").json()["rows"]
    assert rows[0]["checkout"] == "tok_seen_0001" and rows[0]["terms_version"] == "2026-11-18"


def test_consent_node_card_registered():
    card = get_card("website.consent")
    assert card.category == "关口" and "website.consent" in card.emits
