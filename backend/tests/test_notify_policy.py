"""通知策略（Edison 11-19：只推要他动手的，其余进每日汇报）：三个级别、同类同一客人 10 分钟合并、urgent 每小时上限、
记进 core_notify_items、日报「{day}的单和需要你看一眼的」、网站里默认包着策略、check.py 规矩 N1（通知必须写级别）。"""

from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.events import record_event
from app.core.notify import FakeNotifier, LogNotifier, Notifier, build_notifier, unwrap
from app.core.notify_policy import NotifyItem, PolicyNotifier, look_items
from app.main import create_app
from app.ops import report
from app.ops.config import load_config
from app.ops.runtime import get_ops
from tests.conftest import TEST_PASSWORD

REPO = Path(__file__).resolve().parents[2]


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 11, 19, 6, 0, tzinfo=timezone.utc)  # 北京时间 14:00

    def __call__(self) -> datetime:
        return self.t


class Flaky(FakeNotifier):
    """推送会失败的假发法。"""

    def send(self, text, link="", *, level="digest", kind="", who=""):  # type: ignore[override]
        super().send(text, link, level=level, kind=kind, who=who)
        return False


def policy(database, inner: Notifier | None = None, clock: Clock | None = None, **kw) -> PolicyNotifier:
    return PolicyNotifier(inner or FakeNotifier(), database, background=False, now=clock or Clock(), **kw)


def rows(database) -> list[tuple[str, str, str, str]]:
    with database.session(write=False) as db:
        return [(r.level, r.status, r.kind, r.text) for r in db.scalars(select(NotifyItem).order_by(NotifyItem.id))]


# ---------------------------------------------------------------- 三个级别

def test_digest_and_count_are_recorded_not_pushed(database):
    p = policy(database)
    assert p.send("小王 资料齐了，排在明天开工", "/admin/conversations/1", level="digest", kind="资料齐了排期", who="order:1")
    assert p.send("新客户 小王（网页聊天）：在吗", level="count", kind="新客户", who="customer:1")
    assert p.inner.sent == []  # 都不推
    assert [(lv, st, k) for lv, st, k, _ in rows(database)] == [("digest", "digest", "资料齐了排期"), ("count", "count", "新客户")]


def test_urgent_merges_same_kind_same_customer_within_10_minutes(database):
    clock = Clock()
    p = policy(database, clock=clock)
    for i in range(3):
        p.send(f"小王 发来 1 条消息：第{i}句", level="urgent", kind="客人消息", who="customer:1")
        clock.t += timedelta(minutes=2)
    p.send("小李 发来 1 条消息：你好", level="urgent", kind="客人消息", who="customer:2")  # 另一位客人照推
    p.send("#9 第 1 版出水印图失败 3 次", level="urgent", kind="出图失败", who="customer:1")  # 同一位、别的类照推
    assert len(p.inner.sent) == 3 and p.inner.sent[0].endswith("第0句")
    assert [st for _, st, _, _ in rows(database)] == ["pushed", "folded", "folded", "pushed", "pushed"]
    clock.t += timedelta(minutes=11)  # 过了 10 分钟
    p.send("小王 发来 1 条消息：还在吗", level="urgent", kind="客人消息", who="customer:1")
    assert len(p.inner.sent) == 4 and "上一条之后同一位又来了 2 条" in p.inner.sent[-1]


def test_urgent_hourly_cap_overflow_goes_to_report_and_next_push(database):
    clock = Clock()
    p = policy(database, clock=clock, urgent_per_hour=10)
    for i in range(12):
        p.send(f"#{i} 平台上申请了退款", level="urgent", kind="平台退款", who=f"order:{i}")
        clock.t += timedelta(seconds=30)
    assert len(p.inner.sent) == 10
    assert [st for _, st, _, _ in rows(database)].count("overflow") == 2
    with database.session(write=False) as db:
        (g,) = look_items(db, clock.t - timedelta(hours=2), clock.t + timedelta(hours=1))
    assert g["status"] == "overflow" and g["count"] == 2
    clock.t += timedelta(hours=1)
    p.send("#99 修改次数用完了还想改", level="urgent", kind="修改次数用完", who="order:99")
    assert "另有 2 条要紧的没单独推（每小时最多推 10 条），在今晚日报里" in p.inner.sent[-1]


def test_failed_push_recorded_and_text_redacted(database):
    p = policy(database, inner=Flaky())
    assert p.send("小王留了反馈：电话 13812345678 打不通", level="urgent", kind="客人反馈", who="order:3") is False
    ((lv, st, kind, text),) = rows(database)
    assert (lv, st, kind) == ("urgent", "failed", "客人反馈")
    assert "13812345678" not in text and "<手机号>" in text and "13812345678" not in p.inner.sent[0]  # 存的、推的都已脱敏


def test_background_thread_handles_queue(database):
    inner = FakeNotifier()
    p = PolicyNotifier(inner, database)  # 默认后台线程
    assert p.send("助手回 小王 没成功：超时", level="urgent", kind="助手回复失败", who="customer:1") is True
    assert p.send("作废了", level="digest", kind="作废") is True
    assert p.flush(5)
    assert len(inner.sent) == 1 and [st for _, st, _, _ in rows(database)] == ["pushed", "digest"]


# ---------------------------------------------------------------- 接到网站里

def test_website_wraps_sender_with_policy_and_ops_bypasses_it(settings):
    app = create_app(settings)  # 不传通知器：网站自己建，外面包着策略
    n = app.state.notifier
    assert isinstance(n, PolicyNotifier) and isinstance(unwrap(n), LogNotifier)
    assert isinstance(build_notifier(settings), LogNotifier)  # 不给库就是光秃秃的发法
    with TestClient(app) as c:
        n.send("小王 发来 2 条消息，等你在后台「对话」里回", "/admin/conversations/1", level="urgent", kind="客人消息", who="customer:1")
        n.send("小王 资料齐了，排在 11-20 开工", "/admin/conversations/1", level="digest", kind="资料齐了排期", who="order:1")
        n.send("小李 资料齐了，排在 11-21 开工", "/admin/conversations/2", level="digest", kind="资料齐了排期", who="order:2")
        n.send("#2 这单作废了（码退回）：客人不做了", "/admin/orders", level="digest", kind="作废", who="order:2")
        n.send("新客户 小赵：在吗", level="count", kind="新客户", who="customer:3")
        assert n.flush(5)
        assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        body = c.get("/api/admin/ops/report/preview").json()
    look = body["message"]["sections"][1]
    assert look["title"].endswith("的单和需要你看一眼的")
    text = "\n".join(ln["text"] for ln in look["lines"])
    assert "需要你看一眼的（3 条，没单独推）" in text and "资料齐了排期" in text and "作废" in text
    assert "新客户 小赵" not in text and "等你在后台" not in text  # count 不列、推过的不列


def test_daily_report_look_section(settings, database):
    """日报第二段：当天的单（从事件表数）+ 没单独推的（按类别归拢、带后台链接）。也是给 Edison 看的样例。"""
    app = create_app(settings, notifier=FakeNotifier())
    ctx = get_ops(app)
    now = datetime.now(timezone.utc)  # 事件按真实时间记，日报也按真实的今天
    ctx.now_fn = lambda: now
    with database.session() as db:
        for _ in range(3):
            record_event(db, "intake.customer_created", "customer:1", {"channel": "web"})
        for _ in range(2):
            record_event(db, "intake.order_claimed", "order:1", {})
        record_event(db, "intake.stage", "order:1", {"to": "making"})
        record_event(db, "intake.stage", "order:1", {"to": "claimed"})
        record_event(db, "delivery.proof_published", "order:1", {"round": 1})
        record_event(db, "intake.order_completed", "order:1", {})
    clock = Clock()
    clock.t = now
    p = policy(database, clock=clock)
    p.send("小王 资料齐了，排在 11-20 开工（开工后 48 小时内交第一版）", "/admin/conversations/1", level="digest", kind="资料齐了排期", who="order:1")
    p.send("小李 资料齐了，排在 11-21 开工（开工后 48 小时内交第一版）", "/admin/conversations/2", level="digest", kind="资料齐了排期", who="order:2")
    p.send("#7 时限用掉 80%，还没交第一版水印版（11-20 18:00 前要交）", "/admin/orders", level="digest", kind="交付时限快到", who="order:7")
    p.urgent_per_hour = 0  # 假装这一小时推满了
    p.send("#8 平台上申请了退款（制作中），先暂停", "/admin/orders", level="urgent", kind="平台退款", who="order:8")
    with database.session() as db:
        day = report.report_day(now, "Asia/Shanghai", load_config(db).report.time)
        msg, _ = report.build(db, ctx, load_config(db), day, None)
    look = msg.sections[1]
    assert look.title == "今天的单和需要你看一眼的"
    texts = [ln.text for ln in look.lines]
    assert texts[0] == "新客户 3、认领 2、开工 1、交付 1、完成 1"
    assert texts[1] == "需要你看一眼的（4 条，没单独推）："
    assert texts[2].startswith("· 推满了每小时上限，没推：#8 平台上申请了退款")
    assert texts[3].startswith("· 资料齐了排期：小李 资料齐了") and look.lines[3].link.endswith("/admin/conversations/2")
    assert texts[4].startswith("· 交付时限快到：#7 时限用掉 80%")
    assert [s.title for s in msg.sections[2:4]] == ["今天网站运行", "今天业务数据"]
    bj21 = datetime(2026, 11, 19, 13, 0, tzinfo=timezone.utc)  # 北京时间 21:00
    assert report.report_day(bj21, "Asia/Shanghai", "21:00").isoformat() == "2026-11-19"  # 晚上发汇报当天
    assert report.report_day(bj21, "Asia/Shanghai", "09:00").isoformat() == "2026-11-18"  # 早上发就汇报前一天


# ---------------------------------------------------------------- check.py 规矩 N1

def _check():
    spec = importlib.util.spec_from_file_location("check_n1", REPO / "scripts" / "check.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_n1"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_check_rule_notify_must_state_level(tmp_path):
    check = _check()
    f = tmp_path / "backend" / "app" / "intake" / "x.py"
    f.parent.mkdir(parents=True)
    f.write_text('def a(ctx):\n    ctx.notifier.send("新客户", level="count")\n', encoding="utf-8")
    assert check.check_notify_levels(tmp_path) == []
    f.write_text('def a(ctx, call):\n    ctx.notifier.send("新客户")\n    call.ctx.notifier.send("x", level="loud")\n'
                 '    run_node("notify.feishu", call, {"text": "x"})\n    run_node("notify.feishu", call, {"text": "x", "level": "urgent"})\n',
                 encoding="utf-8")
    probs = check.check_notify_levels(tmp_path)
    assert [p.where.rsplit(":", 1)[1] for p in probs] == ["2", "3", "4"]
    assert all(p.rule == "N1 通知要写级别" and p.why and p.fix for p in probs)
    assert check.check_notify_levels(REPO) == []  # 仓库里现在每个调用点都写了
