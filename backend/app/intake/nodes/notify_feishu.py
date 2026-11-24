"""notify.feishu 通知负责人。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register


class NotifyIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    link: str = Field(default="", max_length=300)  # 后台页面，如 /admin/channels（可省）
    level: Literal["urgent", "digest", "count"] = "digest"  # urgent 立刻推 / digest 进日报 / count 日报只给个数（app/core/notify_policy.py）
    kind: str = Field(default="", max_length=32)  # 类别（日报归拢、合并用）
    who: str = Field(default="", max_length=64)  # 哪位客人或哪一单（同类同一个 10 分钟合并）


class NotifyOut(BaseModel):
    sent: bool


def handler(call: NodeCall, data: NotifyIn) -> NodeResult:
    call.ctx.notifier.send(data.text, link=data.link, level=data.level, kind=data.kind, who=data.who)
    return NodeResult(exit="ok", output=NotifyOut(sent=True))


CARD = NodeCard(
    id="notify.feishu",
    name="通知负责人",
    description="通知负责人（不发给客人）：urgent 立刻推到飞书（应用机器人私聊或群机器人，带后台链接；同类同一客人 10 分钟合并、"
                "每小时上限），digest 进当天日报「需要你看一眼的」，count 日报只给个数。",
    category="运营",
    tech=["app/core/notify.py：飞书应用机器人（FEISHU_APP_FILE，现在是 Ruler，正文先脱敏、后台线程发）或群机器人 webhook（FEISHU_WEBHOOK）",
          "测试里换成 FakeNotifier"],
    input_model=NotifyIn,
    output_model=NotifyOut,
    exits=[NodeExit(key="ok", label="发了（发不出去只记日志）", kind="ok")],
    config=["FEISHU_SENDER、FEISHU_APP_FILE、FEISHU_WEBHOOK、NOTIFY_MERGE_MINUTES、NOTIFY_URGENT_PER_HOUR（.env）"],
    emits=["无"],
    listens=["无"],
    replaceable=["企业微信群机器人"],
    failure="发不出去只记日志，不影响业务；限频、令牌过期各重试一次。",
    owner="A",
    status="已有",
)
register(CARD, handler)
