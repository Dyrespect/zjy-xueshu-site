"""把判断、引导、说话规矩拼进接单助手「现在的情况」，以及回复出去前怎么拆、怎么排时间（bot.py 调）。"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.intake.reception import rhythm as rrhythm
from app.intake.reception import style as rstyle
from app.intake.reception.guide import AskPlan
from app.intake.reception.intent import Route
from app.intake.reception.kb import ReceptionKB

HOW = {"facts": "平台事实", "keyword": "关键词", "model": "模型判断", "rules": "规则打分"}


def situation_lines(kb: ReceptionKB, route: Route, plan: AskPlan, *, channel: str) -> list[str]:
    names = [f"{kb.card(i).name if kb.card(i) else i}" for i in route.intents]
    head = "、".join(f"{n}（{'主' if k == 0 else '次'}）" for k, n in enumerate(names)) or "闲聊"
    L = [f"【判断】客人这几句是：{head}｜在回答你上一问：{'是' if route.answering else '否'}（{HOW.get(route.how, route.how)}）"]
    L.append("【这类怎么回】")
    for i in route.intents:
        c = kb.card(i)
        if c is None:
            continue
        line = f"· {c.name}：{c.reply}"
        if c.next:
            line += f" 回完：{c.next}。"
        if c.handoff:
            line += f" 转负责人：{c.handoff}（send_owner_wechat）。"
        L.append(line)
        for s in c.samples[:2]:
            L.append("  示范（学口气，别照抄）：" + s.replace("\n", "／"))
    L += plan.lines()
    seg = kb.style.segments_for(channel)
    banned = "、".join(b.text for b in kb.style.banned[:14])
    if kb.persona.who:
        L.append(f"【你是谁】{kb.persona.name}：{kb.persona.who}。{kb.persona.never}")
    L.append(f"【说话】像在微信里打字：短句、口语，一条一件事，一条一般不超过 {kb.style.max_chars_per_msg} 字；"
             f"想分开发就用空行隔开，最多 {seg} 条。别用：{banned}、列 1234、加粗、表情（后台会查，查到要重写）。")
    return L


def insert_before_next(situation: str, lines: list[str]) -> str:
    marker = "\n【下一步】"
    block = "\n".join(lines)
    if marker in situation:
        head, tail = situation.rsplit(marker, 1)
        return f"{head}\n{block}{marker}{tail}"
    return f"{situation}\n{block}"


@dataclass
class Piece:
    """要排进待发的一条。"""

    text: str
    reasons: list[str] = field(default_factory=list)
    send_after: datetime | None = None


def split_reply(kb: ReceptionKB, reply: str, *, channel: str, budget: int | None) -> list[str]:
    """拆成几条；budget = 这一轮还能用几条（微信客服窗口剩几条减掉固定原文），None 不限。"""
    n = kb.style.segments_for(channel)
    if budget is not None:
        n = max(1, min(n, budget))
    return rstyle.segments(reply, max_segments=n)


def plan_times(kb: ReceptionKB, *, texts: list[str], filler: str, last_customer_at: datetime | None, now: datetime,
               local_now: datetime, customer_chars: int, seed: str) -> list[datetime]:
    rng = random.Random(seed)
    at = last_customer_at or now
    if at > now:
        at = now
    return rrhythm.schedule(kb.rhythm, last_customer_at=at, now=now, local_now=local_now, customer_chars=customer_chars,
                            segments=texts, rng=rng, filler=filler, filler_extra=bool(filler))


def paste_times(kb: ReceptionKB, prev: datetime | None, count: int, seed: str) -> list[datetime | None]:
    if prev is None:
        return [None] * count
    rng = random.Random(seed + "-paste")
    out: list[datetime | None] = []
    t = prev
    for _ in range(count):
        t = rrhythm.paste_after(t, kb.rhythm, rng)
        out.append(t)
    return out


def filler_due(kb: ReceptionKB, route: Route, *, last_filler_at: datetime | None, now: datetime,
               sends_left: int | None) -> bool:
    if route.main not in kb.rhythm.filler_intents or not kb.style.fillers:
        return False
    if sends_left is not None and sends_left < kb.rhythm.wecom_filler_min_sends_left:
        return False
    if last_filler_at is not None and now - last_filler_at < timedelta(hours=kb.rhythm.filler_every_hours):
        return False
    return True
