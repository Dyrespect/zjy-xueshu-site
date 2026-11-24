"""entry.route 入站分流。"""

from __future__ import annotations

from pydantic import BaseModel

from app.channels import inbound
from app.channels.entry_types import InboundMessage
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register


class RouteIn(BaseModel):
    msg: InboundMessage


def handler(call: NodeCall, data: RouteIn) -> NodeResult:
    exit_, out = inbound.route(call, data.msg)
    return NodeResult(exit=exit_, output=out, detail=f"{out.rule} → {out.action}")


CARD = NodeCard(
    id="entry.route",
    name="入站分流",
    description="客人每发一条先到这里：消息里有激活码就去认领；有在走的已认领单就交给助手收资料；没认领的只给问答，"
                "超过每天上限回一句固定的话；没认领时发的文件不收、不下载。不调模型。",
    category="关口",
    tech=["Python；规则表 app/channels/flows/entry_default.json（Pydantic 校验，按顺序取第一条满足的）",
          "run_node 调 code.lookup、order.claim、customer.memory、entry.notice、assistant.sales、confirm.receipt、入口出站节点",
          "订单中枢 service.receive_text / receive_file（claim=False、run_bot=False：认领、叫不叫助手由这里定）"],
    input_model=RouteIn,
    output_model=inbound.RouteOut,
    exits=[NodeExit(key="serve", label="有在走的单：交给助手（文件这时才取）", kind="ok"),
           NodeExit(key="claimed", label="认领上了，发了认领结果和资料清单", kind="ok"),
           NodeExit(key="claim_failed", label="码不对、用过、作废、锁着……回了固定的话", kind="fail"),
           NodeExit(key="visitor_qa", label="没认领：访客问答（只问价、讲交付、发购买方式）", kind="ok"),
           NodeExit(key="visitor_limited", label="没认领、今天额度用完：回一句固定的话（当天一次）", kind="fail"),
           NodeExit(key="file_refused", label="没认领发文件：不收、不下载，回一句（每天一次）", kind="fail"),
           NodeExit(key="confirm", label="客人说确认收货（或叫他去平台点）", kind="ok"),
           NodeExit(key="ignored", label="重复消息、进会话没带码", kind="ok")],
    config=["entry_config.entry_flow：用哪张规则表（默认 entry_default）",
            "visitor_daily_limit、visitor_global_daily_limit（订单中枢设置）：没认领的会话 / 全站每天几条",
            "entry_config.web_visitor_ip_daily：网页没认领时同一 IP 每天几条（默认 60）",
            "entry_config.confirm_phrases：算「确认收货」的说法", "entry_texts：固定话术"],
    emits=["entry.routed", "entry.visitor_limited", "entry.file_refused"],
    listens=["无（各入口收到消息时调）"],
    replaceable=["规则表换文件就换路（例：免费领取流程把「有码」接到免费货号）", "访客问答可换成只回固定话术（不调模型）"],
    failure="自己只做判断，下游节点各自幂等；同一 channel_msgid 第二次来走 ignored；下游抛错：微信这边记 node.failed、"
            "通知负责人、这条跳过（游标照样往前，后台会话里能看到）；网页这边接口回错误，页面提示没发出去、客人重发。",
    owner="D",
    status="要新做",
)
register(CARD, handler)
