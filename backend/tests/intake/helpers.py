"""接单这几块测试共用的东西：建 app（FACTORY_INBOX 指临时目录、工人和发件员关掉）、假模型、造文件。

假模型用 PydanticAI 的 FunctionModel：每一趟第一次请求返回「要调哪些工具」，工具跑完第二次请求返回回复。
剧本函数拿到这一趟的「现在的情况」原文，按需要从里面找文件编号。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic_ai.messages import ModelRequest, ModelResponse, TextPart, ToolCallPart, UserPromptPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.channels.settings import ChannelsSettings
from app.core.storage import LocalStorage
from app.intake.service import Ctx
from app.intake.settings import IntakeSettings
from app.main import create_app

# (要调的工具 [(名字, 参数)], 回复)
Turn = tuple[list[tuple[str, dict[str, Any]]], str]
Script = Callable[[str], Turn]

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def intake_settings(tmp_path: Path, **over: Any) -> IntakeSettings:
    values: dict[str, Any] = dict(
        FACTORY_INBOX=tmp_path / "inbox",
        FACTORY_JOBS=tmp_path / "jobs",
        INTAKE_WORKER=False,
        INTAKE_DEBOUNCE_SECONDS=0,
        # 接待机器人的节奏和开头表明身份（docs/任务单/12_接待机器人_设计.md）：老测试按「马上发、不加开头」写的，
        # 这里关掉；tests/intake/test_reception*.py 自己打开测
        RECEPTION_RHYTHM=False,
        RECEPTION_DISCLOSURE=False,
    )
    values.update(over)
    return IntakeSettings(_env_file=None, **values)


def make_app(settings, notifier, tmp_path: Path, *, model: Any = None, wecom_transport: Any = None, **intake_over: Any):
    app = create_app(settings, notifier=notifier)
    app.state.intake_settings = intake_settings(tmp_path, **intake_over)
    app.state.intake_model = model
    app.state.channels_settings = ChannelsSettings(_env_file=None, CHANNELS_DISPATCH=False, CHANNELS_TICK=False,
                                                   WECOM_API_BASE="https://qyapi.test/cgi-bin")
    app.state.wecom_transport = wecom_transport
    return app


def make_ctx(tmp_path: Path, notifier, **over: Any) -> Ctx:
    return Ctx(intake_settings(tmp_path, **over), LocalStorage(tmp_path / "files"), notifier, "https://hb.example.cn")


def _prompt_of(messages: list[Any]) -> str:
    for m in reversed(messages):
        if isinstance(m, ModelRequest):
            for p in m.parts:
                if isinstance(p, UserPromptPart) and isinstance(p.content, str):
                    return p.content
    return ""


def scripted_model(script: Script | list[Turn]) -> FunctionModel:
    """script：函数（拿情况原文，返回这一趟的工具和回复）或者按顺序的列表（第 n 趟用第 n 个）。"""
    state = {"run": -1, "turn": None}

    def fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
        # 新的一趟 = 只有这一条请求（不带历史）；输出校验没过时 PydanticAI 会追加一条带反馈的 UserPromptPart，那不算新的一趟
        is_new_run = len(messages) == 1
        if is_new_run:
            state["run"] += 1
            prompt = _prompt_of(messages)
            state["turn"] = script(prompt) if callable(script) else script[state["run"]]
            calls, _ = state["turn"]
            if calls:
                return ModelResponse(parts=[ToolCallPart(n, a, tool_call_id=f"c{state['run']}_{i}") for i, (n, a) in enumerate(calls)])
        _, text = state["turn"]
        return ModelResponse(parts=[TextPart(text)])

    return FunctionModel(fn, model_name="假模型")


def file_ids(prompt: str) -> list[int]:
    """从情况原文里找文件编号（「#12 xxx.pdf（用途还没登记）」）。"""
    return [int(x) for x in re.findall(r"#(\d+) [^（]+（用途还没登记）", prompt)]


# ---------------------------------------------------------------- 11-18 订单中枢：造一单

def png(w: int = 1920, h: int = 1080, color: tuple[int, int, int] = (250, 250, 250)) -> bytes:
    """整页图（长边 1920，够出水印图）。"""
    import io

    from PIL import Image, ImageDraw

    im = Image.new("RGB", (w, h), color)
    ImageDraw.Draw(im).text((80, 80), "Slide", fill=(20, 20, 20))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def claimed(db, ctx, *, name: str = "青柠", channel: str = "web", sku: str = "regular-p1", addons=(), platform: str = "fk"):
    """一个会话认领了一枚码（码池的码，认领时建单）→（会话, 订单）。"""
    from app.intake import codes, orders, service
    from app.intake.models import Order

    c = service.get_or_create_customer(db, channel, f"key-{name}-0123456789", nickname=name)
    _, rows = codes.generate_batch(db, sku=sku, count=1, addons=list(addons), platform=platform)
    res = orders.claim(db, ctx, c, rows[0].code, channel=channel)
    assert res.ok, res
    return c, db.get(Order, res.order_id)


CONSENTS = {"consents": ["terms_privacy", "ai_processing", "custom_no_refund"], "terms_version": "2026-11-18",
            "privacy_version": "2026-11-18"}


def give_consent(app, order_id: int) -> None:
    """客人本人勾过三项同意（平台单在确认卡上勾的那一下）。后台代确认之前要有它（出境要本人单独同意）。"""
    from app.core.events import record_event
    from app.intake.runtime import get_runtime

    with get_runtime(app).database.session() as db:
        record_event(db, "website.consent", f"order:{order_id}", {"items": CONSENTS["consents"], "by": "customer", "where": "brief"})


def confirm_brief(db, ctx, o, *, method: str = "customer", note: str = "") -> None:
    """客人对着需求确认卡点「对，开工」（09 需求引导：没确认不开工）。全部按推荐。"""
    from app.intake import brief

    s = brief.load_settings(db)
    answers = {q.key: {"choice": brief.DEFAULT_CHOICE} for q in s.questions if not q.optional}
    brief.save(db, ctx, o, answers, by="customer")
    brief.confirm(db, ctx, o, method=method, by="customer" if method == "customer" else "edison", note=note)


def ready(db, ctx, *, name: str = "青柠", days: int = 7, occasion: str = "组会文献", minutes: int = 15, sku: str = "regular-p1",
          addons=(), purpose: str = "论文", channel: str = "web", platform: str = "fk", brief: bool = True):
    """认领了、需求卡确认了、资料齐了的一单（场合、时长、汇报日、一篇论文）→（会话, 订单）。brief=False：需求卡还没确认。"""
    from datetime import timedelta

    from app.intake import clock, service

    c, o = claimed(db, ctx, name=name, channel=channel, sku=sku, addons=addons, platform=platform)
    if brief:
        confirm_brief(db, ctx, o)
    service.receive_text(db, ctx, c, f"组会汇报，讲 {minutes} 分钟")
    _, f = service.receive_file(db, ctx, c, filename="Affiliation in human-AI interactions.pdf", data=PDF_BYTES)
    f.purpose = purpose
    service.update_order(db, ctx, o, {"occasion": occasion, "duration_min": minutes,
                                      "present_date": clock.today() + timedelta(days=days)})
    return c, o


def pptx_bytes(slides: int = 2, *, hidden: int = 0) -> bytes:
    """最小的 pptx（zip 里 ppt/slides/slideN.xml），模块 E 收成品包时要数页数；hidden 张标成隐藏页。"""
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/presentation.xml", "<p:presentation/>")
        for i in range(1, slides + hidden + 1):
            show = ' show="0"' if i > slides else ""
            z.writestr(f"ppt/slides/slide{i}.xml", f'<p:sld xmlns:p="p"{show}><p:cSld/></p:sld>')
    return buf.getvalue()


def release_held(db, ctx, o) -> None:
    """不加急的单第一版会压到加急承诺时长之后才发（delivery/release.py）：测试里像负责人点「现在就发」那样立刻发。"""
    from app.core.db import utcnow
    from app.delivery import versions
    from app.intake import flow

    if o.flow_step != "publish":
        return
    v = versions.version_of(db, o.id, o.delivery_round + 1)
    if v is not None:
        v.release_at = utcnow()
    flow.emit(db, ctx, o, "proof_ready", by="test", why="测试：现在就发")


def package(db, ctx, o, *, pages: int = 2, finals: bool = True, by: str = "maker", hold: bool = False) -> int:
    """交一版成品包（pptx + 讲稿 + 整页图），返回第几版。hold=False：压着的第一版当场发（老测试照旧）；
    hold=True：照规矩压着（测「最早可发时间」用）。"""
    from app.intake import service
    from app.intake.models import PAGE_KIND

    if finals:
        service.add_deliverable(db, ctx, o, filename="deck.pptx", data=pptx_bytes(pages or 2), kind="PPT")
        service.add_deliverable(db, ctx, o, filename="讲稿.docx", data=b"docx", kind="讲稿")
    for i in range(1, pages + 1):
        service.add_deliverable(db, ctx, o, filename=f"page-{i:02d}.png", data=png(), kind=PAGE_KIND, page_no=i)
    n = service.submit_package(db, ctx, o, by=by)
    if not hold:
        release_held(db, ctx, o)
    return n
