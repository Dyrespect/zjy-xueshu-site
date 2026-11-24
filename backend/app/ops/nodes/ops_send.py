"""ops.send 推送（飞书机器人）。"""

from __future__ import annotations

from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.ops.models_io import OpsMessage, SendOut
from app.ops.sender import build_sender


def handler(call: NodeCall, data: OpsMessage) -> NodeResult:
    ctx = call.ctx
    sender = build_sender(ctx.osettings, ctx.notifier, ctx.transport)
    out = sender.send(data)
    info = {"kind": data.kind, "level": data.level, "title": data.title[:120], "sender": out.sender, "by": call.by}
    if out.delivered:
        record_event(call.db, "ops.sent", f"ops:{data.kind}", info)
        return NodeResult(exit="sent", output=out)
    if not sender.configured:
        return NodeResult(exit="skipped", output=out, detail=out.detail)
    record_event(call.db, "ops.send_failed", f"ops:{data.kind}", {**info, "why": out.detail[:200]})
    return NodeResult(exit="fail", output=out, detail=out.detail)


CARD = NodeCard(
    id="ops.send",
    name="推送（飞书机器人）",
    description="把一条运维消息（告警、恢复、日报、试发）发给 Edison：飞书应用机器人（Ruler，私聊）或飞书群自定义机器人，富文本带后台链接；"
                "没配时只写日志、不报错。发送这一层可以换：加一个实现、改 OPS_SENDER 就行。",
    category="运营",
    tech=["httpx POST 飞书群机器人 webhook（post 富文本，开了签名校验就带签名）",
          "或飞书应用机器人 im/v1/messages（app.core.notify.FeishuAppClient，底座 FEISHU_APP_FILE，和业务通知共用令牌）",
          "或 app.core.notify（底座 FEISHU_WEBHOOK）"],
    input_model=OpsMessage,
    output_model=SendOut,
    exits=[NodeExit(key="sent", label="发出去了", kind="ok"), NodeExit(key="skipped", label="没配机器人，只写了日志", kind="ok"),
           NodeExit(key="fail", label="没发出去", kind="fail")],
    config=["OPS_SENDER（auto / feishu_webhook / feishu_app / core_notifier / log）", "OPS_FEISHU_WEBHOOK_FILE（地址存在文件里，第一行地址、第二行签名密钥）"
            "或 OPS_FEISHU_WEBHOOK、OPS_FEISHU_SECRET（.env，不进库）", "底座 FEISHU_APP_FILE（应用机器人凭证文件，auto 时运维没单独配群就用它）"],
    emits=["ops.sent", "ops.send_failed"],
    listens=["无"],
    replaceable=["feishu_webhook（运维单独一个群）", "feishu_app（飞书应用机器人，私聊）", "core_notifier（走现有通知接口）", "log（只写日志）",
                 "以后：企业微信群机器人"],
    failure="发送失败不抛异常：记 ops.send_failed（只记飞书回的错误码和说明，不记地址）；告警下一轮按静默时间再推，日报失败后台能点「现在发」重发。"
            "webhook 地址、应用的 App Secret 和令牌不进日志、事件、库。",
    owner="运维",
    status="要新做",
)
register(CARD, handler)
