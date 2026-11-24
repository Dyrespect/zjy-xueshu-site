"""pull 模式交接（网站在服务器、工厂在 Mac）：开工时交接包存进平台 → Mac 上 scripts/factory_pull.py 领 → 写进本机 inbox
→ 回执「已领」→ 重跑不重复写；令牌不对拒绝；后台订单卡显示交接状态；pull 模式下「从工厂选」不可用。"""

from __future__ import annotations

import importlib.util
import io
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.intake import clock
from app.intake.models import Handoff
from app.intake.runtime import get_runtime
from tests.conftest import TEST_PASSWORD
from tests.intake.helpers import PDF_BYTES, give_consent, make_app

TOKEN = "pull-token-0123456789abcdefghijklmnopqrstuv"
REPO = Path(__file__).resolve().parents[3]


def _load_puller():
    spec = importlib.util.spec_from_file_location("factory_pull", REPO / "scripts" / "factory_pull.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["factory_pull"] = mod
    spec.loader.exec_module(mod)
    return mod


fp = _load_puller()


@pytest.fixture
def env(settings, notifier, tmp_path):
    jobs = tmp_path / "jobs" / "2026-11-15_组会文献_何小懒" / "成品"
    jobs.mkdir(parents=True)
    (jobs / "deck.pptx").write_bytes(b"PK\x03\x04deck")
    app = make_app(settings, notifier, tmp_path, HANDOFF_MODE="pull", FACTORY_PULL_TOKEN=TOKEN)
    with TestClient(app) as c:
        c.post("/api/auth/login", json={"password": TEST_PASSWORD})
        yield app, c, tmp_path


def _start_order(c: TestClient, nickname: str = "何小懒") -> int:
    """网页客户发码（当场认领）+ 一个 PDF → 后台改称呼、填齐 → 资料齐了自动开工交接。返回订单号。"""
    code = c.post("/api/admin/intake/codes/generate", json={"sku": "regular-p1", "count": 1}).json()["codes"][0]
    key = c.post("/api/channels/web/sessions").json()["key"]
    c.post(f"/api/channels/web/{key}/messages", json={"text": f"组会汇报，讲 15 分钟，我是{nickname}，码 {code}"})
    c.post(f"/api/channels/web/{key}/files", files={"file": ("论文 v2.pdf", PDF_BYTES, "application/pdf")})
    cid = next(r["id"] for r in c.get("/api/admin/intake/conversations").json() if r["last_text"].startswith("[文件]"))
    c.patch(f"/api/admin/intake/conversations/{cid}", json={"nickname": nickname})
    o = c.get(f"/api/admin/intake/conversations/{cid}").json()["order"]
    fid = o["materials"][0]["id"]
    c.post(f"/api/admin/intake/orders/{o['id']}/files/{fid}/purpose", json={"purpose": "论文"})
    present = clock.add_days(clock.today(), 7).isoformat()
    # 09 需求引导：客人在聊天里说「可以」，负责人代确认需求卡（没确认不开工；客人本人要先勾过同意）
    give_consent(c.app, o["id"])
    assert c.post(f"/api/admin/brief/orders/{o['id']}/confirm", json={"note": "客人在聊天里说可以"}).status_code == 200
    c.patch(f"/api/admin/intake/orders/{o['id']}", json={"occasion": "组会文献", "duration_min": 15, "present_date": present})
    return o["id"]


def _order(c: TestClient, oid: int) -> dict:
    cid = next(r["customer_id"] for r in c.get("/api/admin/intake/orders").json() if r["id"] == oid)
    return c.get(f"/api/admin/intake/conversations/{cid}").json()["order"]


def _puller(app, mac_inbox: Path, state: Path) -> "fp.Puller":
    return fp.Puller("http://testserver", TOKEN, mac_inbox, fp.State(state), client=TestClient(app))


def test_pull_stores_package_and_puller_writes_inbox_then_claims(env, notifier):
    app, c, tmp = env
    oid = _start_order(c)
    # 服务器上：交接包存进了平台存储，没往 FACTORY_INBOX 写任何东西
    assert not (tmp / "inbox").exists()
    o = _order(c, oid)
    assert o["stage"] == "making" and o["handoff_mode"] == "pull"
    assert o["handoff"]["status"] == "ready" and o["handoff"]["status_label"] == "待领" and o["handoff"]["folder"] == "何小懒"
    assert any("交接包等 Mac 来领" in s for s in notifier.sent)
    with get_runtime(app).database.session() as db:
        h = db.get(Handoff, o["handoff"]["id"])
        key = h.package_key
        data = get_runtime(app).ctx.storage.read_bytes(key)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert set(zf.namelist()) == {"要求.md", "聊天记录.md", "论文 v2.pdf"}  # 跟 inbox 文件夹里的一样
        assert zf.read("论文 v2.pdf") == PDF_BYTES
        assert "场合：组会文献" in zf.read("要求.md").decode("utf-8")

    # Mac 上：领 → 写进本机 inbox → 回执
    mac_inbox, state = tmp / "mac" / "inbox", tmp / "mac" / "state" / "已领.json"
    p = _puller(app, mac_inbox, state)
    assert fp.run(p) == 0
    folder = mac_inbox / "何小懒"
    assert {x.name for x in folder.iterdir()} == {"要求.md", "聊天记录.md", "论文 v2.pdf"}
    assert (folder / "论文 v2.pdf").read_bytes() == PDF_BYTES
    assert "我是何小懒" in (folder / "聊天记录.md").read_text(encoding="utf-8")
    o = _order(c, oid)
    assert o["handoff"]["status"] == "claimed" and o["handoff"]["status_label"] == "已领"
    assert o["handoff"]["claimed_folder"] == "何小懒" and o["handoff_folder"] == "何小懒"
    assert any("已经领到 Mac：inbox/何小懒/" in s for s in notifier.sent)
    assert not get_runtime(app).ctx.storage.exists(key)  # 领完删交接包（材料原件还在）
    assert c.get(o["materials"][0]["url"]).content == PDF_BYTES
    events = [e["type"] for e in c.get("/api/admin/intake/events", params={"subject": f"order:{oid}"}).json()]
    assert "intake.handoff" in events and "intake.handoff_claimed" in events  # 跨机器传东西留痕

    # 重跑：没有待领的，不重复写
    assert fp.run(_puller(app, mac_inbox, state)) == 0
    assert sorted(x.name for x in mac_inbox.iterdir()) == ["何小懒"]


def test_rerun_after_claim_failed_only_claims_again(env, monkeypatch):
    """写好了、回执没成功（网断了）：下次只补回执，不再写一遍。"""
    app, c, tmp = env
    oid = _start_order(c, "青柚")
    mac_inbox, state = tmp / "mac" / "inbox", tmp / "mac" / "已领.json"
    p = _puller(app, mac_inbox, state)
    monkeypatch.setattr(fp.Puller, "claim", lambda self, hid, folder: (_ for _ in ()).throw(RuntimeError("网断了")))
    assert fp.run(p) == 1
    assert (mac_inbox / "青柚" / "要求.md").is_file()
    assert _order(c, oid)["handoff"]["status"] == "ready"
    monkeypatch.undo()
    assert fp.run(_puller(app, mac_inbox, state)) == 0
    assert sorted(x.name for x in mac_inbox.iterdir()) == ["青柚"]  # 没有「青柚_月-日」第二份
    assert _order(c, oid)["handoff"]["status"] == "claimed"


def test_crash_after_rename_before_bookkeeping_is_not_written_twice(env):
    """改名挪进 inbox 之后、记账之前断了：文件夹在、暂存没了 → 认得出写过了。"""
    app, c, tmp = env
    _start_order(c, "十一")
    mac_inbox, state_path = tmp / "mac" / "inbox", tmp / "mac" / "已领.json"
    items = TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"}).get("/api/handoffs").json()
    (mac_inbox / "十一").mkdir(parents=True)
    (mac_inbox / "十一" / "要求.md").write_text("写好了", encoding="utf-8")
    st = fp.State(state_path)
    st.put(items[0]["id"], folder="十一", written=False, claimed=False)
    assert fp.run(_puller(app, mac_inbox, state_path)) == 0
    assert sorted(x.name for x in mac_inbox.iterdir()) == ["十一"]


def test_existing_folder_gets_suffix_and_dry_run_writes_nothing(env):
    app, c, tmp = env
    oid = _start_order(c)
    mac_inbox, state = tmp / "mac" / "inbox", tmp / "mac" / "已领.json"
    (mac_inbox / "何小懒").mkdir(parents=True)  # 回头客：上一单的文件夹还在
    assert fp.run(_puller(app, mac_inbox, state), dry_run=True) == 0
    assert sorted(x.name for x in mac_inbox.iterdir()) == ["何小懒"] and not state.exists()
    assert _order(c, oid)["handoff"]["status"] == "ready"
    assert fp.run(_puller(app, mac_inbox, state)) == 0
    stamp = clock.today().strftime("%m-%d")
    assert (mac_inbox / f"何小懒_{stamp}" / "要求.md").is_file()
    assert not any((mac_inbox / "何小懒").iterdir())  # 原来那个没被动
    assert _order(c, oid)["handoff"]["claimed_folder"] == f"何小懒_{stamp}"


def test_token_required_and_wrong_token_rejected(env, settings, notifier, tmp_path):
    app, c, _ = env
    _start_order(c)
    good = TestClient(app, headers={"Authorization": f"Bearer {TOKEN}"})
    r = good.get("/api/handoffs")
    assert r.status_code == 200 and len(r.json()) == 1
    assert r.headers["cache-control"] == "no-store"
    plain = TestClient(app)
    assert plain.get("/api/handoffs").status_code == 401  # 没带令牌（后台 cookie 也不算）
    assert c.get("/api/handoffs").status_code == 401
    bad = TestClient(app, headers={"Authorization": "Bearer not-the-token"})
    assert bad.get("/api/handoffs").status_code == 401
    assert bad.get("/api/handoffs/1/package").status_code == 401
    assert bad.post("/api/handoffs/1/claim", json={"folder": "x"}).status_code == 401
    # 同一 IP 连错 5 次锁 10 分钟（这时换对的令牌也不行）
    assert bad.get("/api/handoffs").status_code == 429
    assert good.get("/api/handoffs").status_code == 429
    # 没配令牌：口子关着
    app2 = make_app(settings, notifier, tmp_path / "b", HANDOFF_MODE="pull", FACTORY_PULL_TOKEN="")
    with TestClient(app2, headers={"Authorization": "Bearer "}) as c2:
        assert c2.get("/api/handoffs").status_code == 503


def test_pull_mode_hides_factory_jobs(env):
    app, c, _ = env
    oid = _start_order(c)
    assert c.get("/api/admin/intake/factory-jobs").json() == []
    r = c.post(f"/api/admin/intake/orders/{oid}/deliverables/from-factory",
               json={"job": "2026-11-15_组会文献_何小懒", "filename": "deck.pptx", "kind": "PPT"})
    assert r.status_code == 409 and "上传成品" in r.json()["detail"]
    s = c.get("/api/admin/intake/settings").json()
    assert s["handoff_mode"] == "pull" and s["factory_pull_token"] is True


def test_direct_mode_card_says_written_directly(settings, notifier, tmp_path):
    app = make_app(settings, notifier, tmp_path)
    with TestClient(app) as c:
        c.post("/api/auth/login", json={"password": TEST_PASSWORD})
        oid = _start_order(c)
        o = _order(c, oid)
        assert o["handoff_mode"] == "direct"
        assert o["handoff"]["status"] == "direct" and o["handoff"]["status_label"] == "直接写入"
        assert (tmp_path / "inbox" / "何小懒" / "论文 v2.pdf").read_bytes() == PDF_BYTES
        good = TestClient(app, headers={"Authorization": "Bearer x"})
        assert good.get("/api/handoffs").status_code == 503  # direct 模式没配令牌，领的口子关着
