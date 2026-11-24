"""制作方接口（/api/intake/production）和 scripts/production_cli.py：令牌、开单说明自动生成、
制作方发消息触发机器人、交成品包 → 出水印图 → 发布给客户看（最终版锁着）、改稿单、旧的交成品接口停用；
命令行 list → show → say → deliver 走一遍。"""

from __future__ import annotations

import importlib.util
import io
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select

from app.intake import clock, service
from app.intake.models import Job, Order, Outbox, ProductionMessage
from app.intake.runtime import get_runtime
from tests.intake.helpers import PDF_BYTES, claimed, confirm_brief, make_app, png, pptx_bytes

TOKEN = "prod-token-for-tests-0123456789abcdef"
ROOT = Path(__file__).resolve().parents[3]


def _load_cli():
    spec = importlib.util.spec_from_file_location("production_cli", ROOT / "scripts" / "production_cli.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def env(settings, notifier, tmp_path):
    app = make_app(settings, notifier, tmp_path, PRODUCTION_TOKEN=SecretStr(TOKEN))
    with TestClient(app) as c:
        rt = get_runtime(app)
        with rt.database.session() as db:
            cust, o = claimed(db, rt.ctx, name="青柚")
            confirm_brief(db, rt.ctx, o)
            service.receive_text(db, rt.ctx, cust, "组会汇报，讲 15 分钟，我们组比较看重实验流程")
            _, f = service.receive_file(db, rt.ctx, cust, filename="Affiliation.pdf", data=PDF_BYTES)
            f.purpose = "论文"
            service.update_order(db, rt.ctx, o, {"occasion": "组会文献", "duration_min": 15, "school": "浙江师范大学",
                                                 "present_date": clock.today() + timedelta(days=6),
                                                 "requirement_quotes": ["我们组比较看重实验流程"]})
            assert o.stage == "making"  # 资料齐、今天有名额：开工（交接 + 开单说明）
            oid, cid = o.id, cust.id
        yield app, c, rt, oid, cid


H = {"Authorization": f"Bearer {TOKEN}"}


def test_token_required(env, settings, notifier, tmp_path):
    app, c, rt, oid, _ = env
    assert c.get("/api/intake/production/orders").status_code == 401
    assert c.get("/api/intake/production/orders", headers={"Authorization": "Bearer nope"}).status_code == 401
    for _ in range(3):
        c.get("/api/intake/production/orders", headers={"Authorization": "Bearer nope"})
    assert c.get("/api/intake/production/orders", headers={"Authorization": "Bearer nope"}).status_code == 429
    assert c.get("/api/admin/intake/codes").status_code == 401  # 后台的口子不认制作方令牌
    closed = make_app(settings, notifier, tmp_path / "closed")
    with TestClient(closed) as c2:
        assert c2.get("/api/intake/production/orders", headers=H).status_code == 503


def test_brief_list_show_say_deliver(env):
    app, c, rt, oid, cid = env
    rows = c.get("/api/intake/production/orders", headers=H).json()
    assert [(r["id"], r["customer"], r["maker_state"], r["unread"]) for r in rows] == [(oid, "青柚", "待开", 1)]
    d = c.get(f"/api/intake/production/orders/{oid}", headers=H).json()
    brief = d["messages"][0]
    assert (brief["kind"], brief["direction"]) == ("开单说明", "to_maker")
    for must in ("档位：常规 · 1 篇；页数上限 30 页", "场合：组会文献", "时长：15 分钟", "学校：浙江师范大学",
                 "我们组比较看重实验流程", "Affiliation.pdf（论文）", "材料在：inbox/青柚/", "开工后 7 小时内交第一版水印版"):  # 5 + 余量 2
        assert must in brief["text"]
    assert d["inbox_folder"] == "青柚" and d["materials"] == [{"name": "Affiliation.pdf", "purpose": "论文", "size": len(PDF_BYTES)}]
    assert "storage" not in str(d)
    assert c.post(f"/api/intake/production/orders/{oid}/read", headers=H).json() == {"read": 1}
    assert c.post(f"/api/intake/production/orders/{oid}/start", headers=H).json()["maker_state"] == "在做"

    # 制作方问一个问题 → 记下、给这个客户排一趟机器人
    r = c.post(f"/api/intake/production/orders/{oid}/messages", headers=H, json={"kind": "问题", "text": "要不要放研究团队介绍？"})
    assert r.status_code == 200 and r.json()["direction"] == "to_sales"
    with rt.database.session() as db:
        assert db.scalar(select(Job).where(Job.customer_id == cid)).status == "pending"
    assert c.post(f"/api/intake/production/orders/{oid}/messages", headers=H, json={"kind": "成品", "text": "x"}).status_code == 422

    # 旧的交成品接口停用（会绕过水印和已完成关口）
    assert c.post(f"/api/intake/production/orders/{oid}/deliverables", headers=H,
                  files=[("files", ("deck.pptx", b"PK", "application/octet-stream"))]).status_code == 410
    # 只交 pptx、没有整页图：不收
    bad = c.post(f"/api/intake/production/orders/{oid}/package", headers=H,
                 files=[("files", ("deck.pptx", b"PK\x03\x04deck", "application/octet-stream"))])
    assert bad.status_code == 409 and "整页图" in bad.json()["detail"]
    small = c.post(f"/api/intake/production/orders/{oid}/package", headers=H,
                   files=[("files", ("deck.pptx", b"PK", "x")), ("pages", ("page-01.png", png(800, 450), "image/png"))])
    assert small.status_code == 409 and "缩略图" in small.json()["detail"]
    # 交成品包 → 出水印图 → 发布：只发交付页链接，最终版锁着
    r = c.post(f"/api/intake/production/orders/{oid}/package", headers=H, data={"note": "第一版"},
               files=[("files", ("deck.pptx", pptx_bytes(2), "application/octet-stream")),
                      ("files", ("讲稿.docx", b"docx", "application/octet-stream")),
                      ("pages", ("page-02.png", png(), "image/png")), ("pages", ("page-01.png", png(), "image/png"))])
    assert r.status_code == 200, r.text
    r = r.json()
    assert r["round"] == 1 and r["files"] == ["deck.pptx", "讲稿.docx"] and r["pages"] == 2 and r["stage_label"] == "已交水印版"
    with rt.database.session() as db:
        o = db.get(Order, oid)
        assert o.stage == "watermarked" and o.maker_done_at is not None
        obs = list(db.scalars(select(Outbox).where(Outbox.category == "交付").order_by(Outbox.id)))
        assert [ob.kind for ob in obs] == ["text"] and "确认收货" in obs[0].text  # 水印阶段只发链接
        done = db.scalar(select(ProductionMessage).where(ProductionMessage.kind == "成品"))
        assert done.relayed_at is not None

    # 客户在交付页提修改 → 制作方会话里出现改稿单
    token = r["delivery_url"].rsplit("/", 1)[1]
    c.post(f"/api/delivery/{token}/revision", data={"text": "第 2 页结果图换成原文的图 3"})  # 这版共 2 页（模块 E 查页码）
    msgs = c.get("/api/intake/production/messages", headers=H).json()
    assert [(m["kind"], m["order_id"]) for m in msgs] == [("改稿单", oid)] and "图 3" in msgs[0]["text"]
    rows = c.get("/api/intake/production/orders", headers=H).json()
    assert rows[0]["maker_state"] == "改稿中" and rows[0]["unread"] == 1


def test_cli_list_show_say_deliver(env, tmp_path):
    app, c, rt, oid, cid = env
    cli = _load_cli()
    c.headers.update(H)

    def run(*argv):
        out = io.StringIO()
        code = cli.main(list(argv), client=c, out=out)
        return code, out.getvalue()

    code, out = run("list")
    assert code == 0 and f"#{oid}  青柚  待开  组会文献 15 分钟" in out and "[1 条新消息]" in out
    code, out = run("show", "青柚")  # 写客户称呼也行
    assert code == 0 and "材料在：inbox/青柚/" in out and "系统（开单说明）  [新]" in out and "我们组比较看重实验流程" in out
    assert "[新]" not in run("show", f"#{oid}")[1]  # 看过了
    code, out = run("say", str(oid), "初稿做了一半，明天中午前能交", "--kind", "进度")
    assert code == 0 and "发给业务员了" in out
    deck = tmp_path / "青柚_组会汇报.pptx"
    deck.write_bytes(pptx_bytes(2))
    script = tmp_path / "讲稿.docx"
    script.write_bytes(b"docx")
    pages = tmp_path / "预览"
    pages.mkdir()
    for i in (1, 2):
        (pages / f"page-{i:02d}.png").write_bytes(png())
    code, out = run("deliver", str(oid), str(deck), "--pages", str(pages))
    assert code == 1  # 模块 E：讲稿也是必交的最终版，缺了不收（原因打在 stderr）
    code, out = run("deliver", str(oid), str(deck), str(script), "--pages", str(pages))
    assert code == 0 and "交了第 1 版：青柚_组会汇报.pptx、讲稿.docx，整页图 2 张" in out and "已交水印版" in out and "/d/" in out
    with rt.database.session() as db:
        assert db.get(Order, oid).stage == "watermarked"
        kinds = [m.kind for m in service.production_messages(db, db.get(Order, oid))]
        assert kinds == ["开单说明", "进度", "成品"]
    code, out = run("deliver", str(oid), str(tmp_path / "没有这个.pptx"))
    assert code == 1


def test_cli_config_reads_env_file(tmp_path, monkeypatch):
    cli = _load_cli()
    monkeypatch.delenv("PRODUCTION_SERVER", raising=False)
    monkeypatch.delenv("PRODUCTION_TOKEN", raising=False)
    env = tmp_path / ".env"
    env.write_text("PUBLIC_BASE_URL=http://127.0.0.1:8760\nPRODUCTION_TOKEN='abc'\n", encoding="utf-8")
    assert cli.load_config(env) == ("http://127.0.0.1:8760", "abc")
    env.write_text("PRODUCTION_SERVER=https://hb.example.cn/\nPUBLIC_BASE_URL=http://x\nPRODUCTION_TOKEN=t\n", encoding="utf-8")
    assert cli.load_config(env) == ("https://hb.example.cn", "t")
    with pytest.raises(cli.CliError):
        cli.make_client("http://127.0.0.1:8760", "")
