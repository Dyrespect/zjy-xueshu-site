"""接单助手的问答卡（访客问答照着说，也排进产品介绍的「常见问题」）：默认值和填占位符。

卡的原文来自模块 G 的 `学术汇报/docs/方案/2026-11-18_生态顶层设计/文案草稿/10_助手问答卡.md`（只有一份，放设置 faq，
后台「设置」页能改）。价格、时限一律写占位符（`00_占位符和现价.md`），放进助手的情况之前由 fill() 按设置现填，
以后压价只改设置。`a` 是要说的事实，助手用自己的话说；`hint` 只给助手看（调哪个工具、什么时候转负责人）；
`channels`：bot 助手、site 网页介绍、gzh 公众号、platform 平台。入口模块（D）接进来的（入口设计第三节第 8 条）。
"""

from __future__ import annotations

import re
from typing import Any

INTRO_URL_DEFAULT = "https://psyppt.pilipala.zj.cn"  # psyppt 官网（价目、交付说明、退款）；设置 entry_texts.intro_url 可改
CN_NUM = {1: "一", 2: "两", 3: "三", 4: "四", 5: "五"}

DEFAULT_FAQ: list[dict[str, Any]] = [
    {"q": "多少钱｜价格｜怎么收费", "a": "按汇报时长和要讲几篇定价，{起价} 元起，都含 {含改轮数} 轮修改。",
     "hint": "客人说了时长和篇数就用 quote_price 算出这一档的价和时限再说，不自己算；没说就问讲多久、讲几篇。附上价目：{介绍页链接}#price", "channels": ["bot"]},
    {"q": "多久能好｜什么时候交", "a": "材料齐了开工，开工后交水印版：{时限一句}。排队、看稿和改稿的时间不算在内。",
     "hint": "问哪天能交，用 quote_price 看排期，说「最早 X 能交」，不说「保证」「肯定」。", "channels": ["bot", "site", "gzh", "platform"]},
    {"q": "能改几次｜怎么改", "a": "含 {含改轮数} 轮修改：看完水印版把要改的一次说齐。再改一轮另加 {加购:再改一轮} 元。原材料范围内的都算修改；换题目、加新材料、改时长算新的一单。",
     "hint": "", "channels": ["bot", "site", "gzh", "platform"]},
    {"q": "做不做问卷、访谈", "a": "用问卷、访谈做的研究，论文和开题汇报照常做，问卷和访谈的流程会画成图。不接的是只有问卷原始数据、访谈录音或逐字稿，要先分析、编码才能汇报的。",
     "hint": "判断不了客人的材料属于哪种，用 send_owner_wechat。", "channels": ["bot", "site", "gzh", "platform"]},
    {"q": "做不做数据分析、建模｜能不能写论文、改论文", "a": "数据预处理过的，可以做简单的分析放进汇报；没预处理的原始数据、建模不做。不写论文、不改论文、不编数据。",
     "hint": "拿不准他的数据算不算预处理过、要的分析算不算简单，或者他坚持要做不做的，用 send_owner_wechat。", "channels": ["bot"]},
    {"q": "能不能做英文", "a": "可以做英文汇报，下单前说一声。", "hint": "", "channels": ["bot"]},
    {"q": "怎么确认收货｜什么时候拿到可编辑的 PPT", "a": "先交水印版。网页下单的，满意了点「确认收货」就发可编辑的 PPT 和讲稿；每次水印版交出后 {自动确认天数} 天没回应，系统自动确认。在闲鱼、小红书、抖音买的，平台订单完成后发。",
     "hint": "", "channels": ["bot", "site", "gzh"]},
    {"q": "怎么确认收货｜什么时候拿到可编辑的 PPT", "a": "先交水印版。平台订单完成后（你点确认收货，或平台自动确认），发可编辑的 PPT 和讲稿。",
     "hint": "", "channels": ["platform"]},
    {"q": "能退款吗", "a": "开工前想撤单可以退。这是按你的材料单独做的定制服务，开始制作后不支持仅退款；不满意先说哪里要改，含 {含改轮数} 轮修改。",
     "hint": "已经开工还要退、或者投诉，用 send_owner_wechat，不自己答应。", "channels": ["bot", "site", "gzh", "platform"]},
    {"q": "篇数怎么算｜页数怎么算", "a": "篇数是要讲进 PPT 的论文或报告份数，开题报告、你自己的毕业论文各算一篇，模板和老师意见不算。页数只算内容页：{页数说明}。",
     "hint": "", "channels": ["bot"]},
    {"q": "能加急吗", "a": "{可加急的档}能加急，加 {加购:加急} 元，材料要一次发齐，每天名额有限；没在加急时限内交就退这笔钱。",
     "hint": "能不能排上用 quote_price（rush=true）看。", "channels": ["bot"]},
    {"q": "只有题目、没有论文能做吗｜帮我找文献", "a": "可以加「帮我找文献」，加 {加购:找文献} 元：按题目找相关研究做进 PPT，标准时限多 {找文献加时} 小时，不能加急。只在我们网页上能加。",
     "hint": "", "channels": ["bot"]},
    {"q": "材料会不会外泄", "a": "你发来的材料、数据和草稿不公开，也不拿去当示例。", "hint": "", "channels": ["bot"]},
    {"q": "是 AI 做的吗", "a": "PPT 由 AI 做：Claude 定框架、逐页审读，页面由另一个模型按我们磨出来的心理学汇报标准做。",
     "hint": "", "channels": ["bot", "site", "gzh", "platform"]},
    {"q": "你是真人吗", "a": "我是 PsyEngine 的 AI 接单助手。", "hint": "要找真人，用 send_owner_wechat。", "channels": ["bot"]},
    {"q": "能先看看做出来什么样吗｜样例", "a": "可以，直接发几份我们做的样张（讲公开论文的，带水印）；公众号 PsyEngine 每天发一篇免费的文献汇报 PPT，也能看到完整的稿子。",
     "hint": "用 send_sample 发一份样张 PDF；不拿别的客户的 PPT 给人看。", "channels": ["bot"]},
    {"q": "能用学校模板、放校徽吗", "a": "可以。说一下学校就用上校徽和配色；有学校或课题组的模板，发过来就套。", "hint": "", "channels": ["bot"]},
    {"q": "不知道讲多久｜超过一小时或很多篇", "a": "按老师给的时间选，拿不准往长一档选。超过 {最长分钟} 分钟或 {最多篇数} 篇以上，先说一下情况，看能不能做、怎么报价。",
     "hint": "超出范围的用 send_owner_wechat。", "channels": ["bot"]},
    {"q": "怎么买｜激活码是什么", "a": "网页下单付款后，页面直接给激活码；在闲鱼、小红书、抖音买的，激活码在发货消息里。拿到码发给我（PSY- 开头）或打开兑换网址，认领后再交材料。",
     "hint": "还没买：用 send_payment 发下单方式；付款前用 send_terms 发交付说明和注意事项。", "channels": ["bot"]},
    {"q": "能便宜点吗｜打折", "a": "价格按档位定，不单独打折。", "hint": "坚持要谈，用 send_owner_wechat。", "channels": ["bot"]},
    {"q": "能不能只做一部分", "a": "可以，说清要做哪几部分、讲多久。", "hint": "按这部分讲多久用 quote_price 报。", "channels": ["bot"]},
    {"q": "老师以前问过的问题要不要发", "a": "要，认领后发过来，做的时候会照顾到。", "hint": "", "channels": ["bot"]},
]

_PH = re.compile(r"\{([^{}]+)\}")
ADDON_BY_NAME = {"再改一轮": "revision", "加急": "rush", "找文献": "find_refs"}


def values(cfg: Any) -> dict[str, str]:
    """按现在的设置算出每个占位符的值（00_占位符和现价.md 第一、三节里问答卡用到的那几个）。"""
    from app.intake import pricing
    from app.intake.config_store import dec

    tiers = cfg.tiers_sorted()
    prices = [dec(p) for t in tiers for p in t.prices.values()]
    prices = [p for p in prices if p is not None]
    rush = [t.name for t in tiers if t.rush]
    out = {
        "起价": pricing.fmt_money(min(prices)) if prices else "",
        "含改轮数": str(cfg.revisions_included),
        "时限一句": "、".join(f"{t.name} {pricing.promised_hours(cfg, t)} 小时" for t in tiers),
        "自动确认天数": str(cfg.auto_confirm_days),
        "页数说明": cfg.page_rule_text.rstrip("。"),
        "可加急的档": ("、".join(rush) + f"{CN_NUM.get(len(rush), str(len(rush)))}档") if len(rush) > 1 else (f"{rush[0]}档" if rush else "（暂时没有）"),
        "找文献加时": str(cfg.find_refs_extra_hours),
        "最长分钟": str(max((t.max_minutes for t in tiers), default=0)),
        "最多篇数": str(max((b.max_papers for b in cfg.paper_bands), default=0)),
        "介绍页链接": (cfg.entry_texts.get("intro_url") or INTRO_URL_DEFAULT).rstrip("/") + "/",
    }
    for name, key in ADDON_BY_NAME.items():
        a = cfg.addon(key)
        out[f"加购:{name}"] = a.price if a is not None else ""
    return out


def fill(text: str, vals: dict[str, str]) -> str:
    """把 {占位符} 换成值；认不得的原样留着（测试 F2 会抓出来）。"""
    return _PH.sub(lambda m: vals.get(m.group(1), m.group(0)), text or "")


def cards_for(cfg: Any, channel: str = "bot") -> list[tuple[str, str, str]]:
    """这个渠道用的卡（填好占位符）：[(q, a, hint)]。"""
    vals = values(cfg)
    out = []
    for c in cfg.faq:
        chans = getattr(c, "channels", None) or ["bot"]
        if channel in chans:
            out.append((c.q, fill(c.a, vals), fill(getattr(c, "hint", "") or "", vals)))
    return out
