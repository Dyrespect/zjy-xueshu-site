"""entry.redeem_page 兑换网页。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.channels import redeem
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register


class RedeemIn(BaseModel):
    action: Literal["view", "claim_web"] = "view"
    code: str = Field(default="", max_length=200, description="地址里的码，原样")
    web_key: str | None = Field(default=None, description="这个浏览器存的网页聊天 key（有就带上）")
    available: list[str] = Field(default_factory=list, description="现在能用的入口（兑换页接口按 EntrySpec.available 算好）")
    person_id: int | None = Field(default=None, description="当前登录的客户（12 号设计：认领前先登录）；没登录 None")
    login_required: bool = Field(default=False, description="这台设备认领前要不要先登录（后台开关开着且有登录方式）")
    login_label: str = Field(default="", description="已登录时显示的账号（微信 / 手机 138****5678）")


class RedeemNodeOut(BaseModel):
    view: redeem.RedeemOut | None = None
    claimed: redeem.ClaimWebOut | None = None
    refused: str = ""
    refused_status: int = 409


def handler(call: NodeCall, data: RedeemIn) -> NodeResult:
    if data.action == "view":
        return NodeResult(exit="show", output=RedeemNodeOut(view=redeem.view(
            call, data.code, data.web_key, data.available, person_id=data.person_id, login_required=data.login_required,
            login_label=data.login_label)))
    try:
        out = redeem.claim_web(call, data.code, data.web_key, person_id=data.person_id, login_required=data.login_required)
    except redeem.RedeemRefused as e:
        return NodeResult(exit="refused", output=RedeemNodeOut(refused=e.detail, refused_status=e.status), detail=e.detail)
    return NodeResult(exit="claimed_web", output=RedeemNodeOut(claimed=out))


CARD = NodeCard(
    id="entry.redeem_page",
    name="兑换网页",
    description="客人从平台发货内容点开 /c/{CODE}：第一步登录（12 号设计：微信里静默、电脑扫码、手机号），第二步认领到这个账号；"
                "码不能用说清楚为什么；已认领的、是这个人（账号或浏览器）的显示进度，不是的不给任何订单信息。页面上写清激活码从哪来、在哪买。",
    category="入口",
    tech=["FastAPI GET /api/channels/redeem/{code}、POST /api/channels/redeem/{code}/web、GET /api/channels/redeem（app/channels/redeem_router.py）",
          "React pages/redeem/（/c、/c/:code）+ 区块 blocks/redeem-card", "run_node 调 code.lookup、order.claim、customer.memory、entry.notice",
          "按钮来自入口登记处 entries.all_specs()"],
    input_model=RedeemIn,
    output_model=RedeemNodeOut,
    exits=[NodeExit(key="show", label="给页面看的状态和按钮", kind="ok"),
           NodeExit(key="claimed_web", label="认领上了（或并进了码的主人），跳聊天", kind="ok"),
           NodeExit(key="refused", label="作废、过期、被别人在网页认领了、码不对", kind="fail")],
    config=["entry_config.redeem_entries：页面放哪几个入口（默认全部）", "entry_config.redeem_ip_hourly：同一 IP 每小时查几次（默认 60）",
            "entry_config.buy_places、code_hint：激活码从哪来、在哪买"],
    emits=["entry.redeem_viewed（状态、码尾号，不记全码）", "entry.redeem_claimed_web"],
    listens=["无"],
    replaceable=["加入口不改页面：新入口登记 EntrySpec 就多一个按钮"],
    failure="查询只读；网页认领走 order.claim 幂等（同一浏览器再点 = 直接跳聊天）；要登录时没登录 401；被别的账号认领了 409，"
            "不给任何那单的信息；按 IP 限流，超了 429。",
    owner="D",
    status="要新做",
)
register(CARD, handler)
