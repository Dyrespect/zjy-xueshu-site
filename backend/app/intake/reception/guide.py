"""引导：这一轮最多问哪一件（设计第五、六节）。

- 最小必问：售前只为报价问「讲多久、几篇」、为排期问「哪天汇报」；认领后只追开工必须的「场合、材料、哪天汇报、时长」，
  其余（听众、语言、模板、重点、不要什么）交给需求卡点选，不在聊天里问。
- 一次只问一件；先回客人的话，再顺带问。
- 刚问过、客人没接：这一轮不再问（先回他的话）；同一件问满 max_times 次，聊天里不再问，交给需求卡和提醒。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.intake.reception.kb import Ask, ReceptionKB

DURATION_RE = re.compile(r"\d+\s*(分钟|min|分)|半小时|半个小时|一小时|一个小时|[一二三四五六七八九十两]+\s*分钟")
PAPERS_RE = re.compile(r"(\d+|[一二两三四五六七八九十])\s*篇")
DATE_RE = re.compile(r"(周|星期|礼拜)[一二三四五六日天]|\d+\s*(号|日)|\d+\s*月|明天|后天|大后天|今天|今晚|下周|这周|下下周|月底|月初")
NO_ASK_INTENTS = {"chitchat", "escalate", "refund", "ask_bot", "invoice", "special", "confirm_ok"}


@dataclass
class AskPlan:
    ask: Ask | None = None
    why: str = ""
    held: list[str] = field(default_factory=list)  # 这一轮先不问的（刚问过 / 问够次数了）

    def lines(self) -> list[str]:
        out: list[str] = []
        if self.ask is not None:
            out.append(f"【这一轮最多问一件】{self.ask.label}——参考说法「{self.ask.say}」（用自己的话，先回他的话再顺带问）")
        else:
            out.append(f"【这一轮不用问】{self.why or '没有要问的'}")
        if self.held:
            out.append("【先别问】" + "；".join(self.held))
        return out


def times_asked(ask: Ask, bot_texts: list[str]) -> int:
    return sum(1 for t in bot_texts if any(m and m in t for m in ask.markers))


def known_in_chat(customer_texts: list[str]) -> dict[str, bool]:
    joined = "\n".join(customer_texts)
    return {"duration": bool(DURATION_RE.search(joined)), "papers": bool(PAPERS_RE.search(joined)),
            "date": bool(DATE_RE.search(joined))}


def needed_keys(*, serving: bool, stage: str, missing: list[str], brief_ok: bool, customer_texts: list[str],
                main_intent: str) -> list[str]:
    """按顺序列出还缺、该在聊天里问的几件。missing 用 BotDeps.still_missing() 的结果（认领后）。"""
    if not serving:
        k = known_in_chat(customer_texts)
        out = []
        if not k["duration"]:
            out.append("duration_papers")
        if not k["date"] and main_intent in ("ask_time", "ask_price", "answer", "ask_scope"):
            out.append("present_date")
        return out
    if stage not in ("claimed", "collecting", ""):
        return []
    out = []
    for m in missing:
        if m == "场合":  # 场合先问：知道了系统才把这个场合要的资料整张发过去
            out.append("occasion")
        elif m.startswith("材料"):
            out.append("materials")
        elif m == "哪天汇报":
            out.append("present_date")
        elif m == "讲几分钟":
            out.append("duration_papers")
        elif "点头" in m:
            out.append("duration_confirm")
    if not out and not brief_ok:
        out.append("brief")
    # 先场合和材料，再哪天汇报（人多要排班），再时长：负责人自己就是这个顺序（「你发我材料哦，然后和我说一下什么时候要用」）
    order = {"occasion": 0, "materials": 1, "present_date": 2, "duration_papers": 3, "duration_confirm": 4, "brief": 5}
    return sorted(dict.fromkeys(out), key=lambda k: order.get(k, 9))


def plan(kb: ReceptionKB, *, keys: list[str], intents: list[str], bot_texts: list[str], last_bot: str,
         answering: bool) -> AskPlan:
    """bot_texts：助手最近说过的话（旧→新），last_bot：上一句。"""
    if intents and intents[0] in NO_ASK_INTENTS:
        return AskPlan(None, f"这句是「{intents[0]}」，这轮只回他的话，不追问")
    held: list[str] = []
    for key in keys:
        ask = kb.ask(key)
        if ask is None:
            continue
        n = times_asked(ask, bot_texts)
        if n >= ask.max_times:
            held.append(f"{ask.label}（问过 {n} 次了，聊天里不再问，交给需求卡和提醒）")
            continue
        if last_bot and any(m and m in last_bot for m in ask.markers) and not answering:
            held.append(f"{ask.label}（上一句刚问过、他没接，这轮先回他的话）")
            continue
        return AskPlan(ask, "", held)
    return AskPlan(None, "该问的都有了" if not held else "该问的这轮都先放着", held)
