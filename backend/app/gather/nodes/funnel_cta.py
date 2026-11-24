"""funnel.cta 下单和关注公众号的入口：图库页头、搜索结果最后一行、领到图库那段话、插件返回里，都带来源。"""

from __future__ import annotations

from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.gather.config import load_config
from app.gather.models_io import CtaIn, CtaOut
from app.gather.site import href, order_url


def handler(call: NodeCall, data: CtaIn) -> NodeResult:
    gs = call.ctx.settings
    cfg = call.ctx.cfg or load_config(call.db)
    if data.target == "order":
        out = CtaOut(url=order_url(gs, data.placement), text="直接下单")
    elif data.target == "site":
        out = CtaOut(url=href(gs, "main", "/"), text=cfg["cta_text"])
    else:  # 公众号：个人订阅号没有网址，只给一句话
        out = CtaOut(url="", text=f"公众号 {cfg['gzh_name']}")
    if data.record:
        record_event(call.db, "funnel.cta_click", f"cta:{data.placement}",
                     {"placement": data.placement, "target": data.target, "visitor": data.visitor[:40]})
    return NodeResult(exit="ok", output=out)


CARD = NodeCard(
    id="funnel.cta",
    name="下单和关注公众号的入口",
    description="在图库页头（做汇报 PPT 看这里 → 官网）、搜索结果最后一行、领到图库那段话、插件返回里放两个入口：做汇报 PPT（官网、下单页）、"
                "关注公众号（收图库更新和每天的免费 PPT）。去下单页的链接带 from=tuku_<位置>，订单上记 source，算得出图库带来几单。只这几处，不弹窗、不浮动。",
    category="获客",
    tech=["站点地图 app/gather/site_map.json + .env 的 SITE_MAIN_URL / SITE_APP_URL", "FastAPI POST /api/gather/cta（点击记录）",
          "下单页 /order 接 from（channel.web，模块 B 已做：订单 source）", "前端区块 site-header、search-results、all-library-dialog"],
    input_model=CtaIn,
    output_model=CtaOut,
    exits=[
        NodeExit(key="ok", label="给了链接", kind="ok"),
        NodeExit(key="hidden", label="目标没配、不显示", kind="ok"),
    ],
    config=["cta_text：页头那句字（后台聚人设置）", "gzh_name：公众号名字", "SITE_MAIN_URL、SITE_APP_URL：官网、下单页网址前缀"],
    emits=["funnel.cta_click（placement、target、visitor）"],
    listens=["无"],
    replaceable=["下单目标：下单页 / 官网 / 微信客服"],
    failure="点击记录发完不等；目标没配就不显示（页面上不放没做出来的东西）。",
    owner="L",
    status="要改",
)
register(CARD, handler)
