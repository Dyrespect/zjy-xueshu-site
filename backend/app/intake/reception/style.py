"""说话：去 AI 味的检查、拆成几条、表明身份（设计第七、八节）。

- 禁用说法（知识库 style.banned / banned_patterns）在回复出去之前由代码查：查到就让模型重写（PydanticAI 输出校验 + ModelRetry），
  最后一次还不行就由代码删掉那几处再发，不让一条坏回复卡住客人。
- 被问「是不是机器人」时回复里必须照实说是 AI 助手；任何时候不许说自己是真人（合规红线，查到一样重写）。
- 模型用空行把一条回复分成几条（像微信里连发几条短的）；条数按渠道封顶（微信客服 48 小时只能发 5 条，默认最多 2 条）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.intake.reception.kb import ReceptionKB

_AI_WORD = re.compile(r"AI|ai|人工智能|智能助手|机器人")
# 没算过的时间承诺（Edison 11-19：删掉「现在买的话最早明天就能给」「今晚能出」这类说法；时间只照工具算的说）
_TIME_PROMISE = re.compile(r"(今晚|今天(晚上|下午|中午)|明早|明天(一早|上午|中午|下午|晚上)?|后天|马上|一会儿|很快)[^，。！？\n]{0,6}(能|可以|就)?[^，。！？\n]{0,3}(给|发|交|出|好|做完)")
_PRICE = re.compile(r"\d+\.\d|\d+\s*元")
_HUMAN_CLAIM = re.compile(r"我(就)?是真人|我不是(机器人|AI|ai|人工智能)|我是负责人本人")


@dataclass
class Problem:
    what: str
    why: str


def problems(text: str, kb: ReceptionKB, intents: list[str] | None = None, recent: list[str] | None = None, *,
             time_checked: bool = True, no_price: bool = False) -> list[Problem]:
    """回复里不许有的东西（要重写的）。recent：助手最近说过的几条（同一句话不说两遍，OpenAI 的 Variety 规则）。
    time_checked=False：这一轮没调报价、查进度这类工具，回复里就不许有「今晚能给」「明天就能交」这类没算过的时间；
    no_price=True：超出档位要转负责人，不许报价。"""
    out: list[Problem] = []
    if not time_checked and (m := _TIME_PROMISE.search(text)):
        out.append(Problem(f"「{m.group(0)}」", "时间只照工具算的说（quote_price 的标准时限和排期、check_progress 查到的），不现编"))
    if no_price and (m := _PRICE.search(text)):
        out.append(Problem(f"「{m.group(0)}」", "超出最长一档或最多篇数：不报价，直接转负责人"))
    for part in segments(text, max_segments=99):
        if len(part) >= 6 and any(part == r.strip().rstrip("。") for r in (recent or [])[-6:]):
            out.append(Problem(f"「{part[:20]}」", "跟你前面说过的一模一样，换个说法"))
            break
    for b in kb.style.banned:
        if b.text in text:
            out.append(Problem(f"「{b.text}」", b.why))
    for p in kb.style.banned_patterns:
        m = re.search(p.pattern, text)
        if m:
            out.append(Problem(f"「{m.group(0).strip() or p.pattern}」", p.why))
    if _HUMAN_CLAIM.search(text):
        out.append(Problem("说自己是真人", "合规红线：你是 AI 助手，不能说自己是真人或负责人"))
    if intents and "ask_bot" in intents and not _AI_WORD.search(text):
        out.append(Problem("没说自己是 AI 助手", "客人在问是不是机器人：照实说是 AI 助手，负责人会看记录"))
    if text.count("？") + text.count("?") >= 3:
        out.append(Problem("问了好几个问题", "一次只问一件"))
    return out


def retry_message(found: list[Problem]) -> str:
    items = "；".join(f"{p.what}：{p.why}" for p in found[:6])
    return f"这条回复要重写：{items}。照负责人平时的口气，短句、口语，意思不变。"


def scrub(text: str, kb: ReceptionKB) -> str:
    """重写几次还不行时的兜底：删掉禁用的词和格式，不改别的意思。"""
    t = text
    t = re.sub(r"(?m)^\s*(\d+[.、)）]|[-*•])\s*", "", t)
    t = t.replace("**", "")
    t = re.sub(r"[！!]{2,}", "！", t)
    t = re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", "", t)
    t = t.replace("您", "你")
    t = _HUMAN_CLAIM.sub("我是 AI 助手", t)
    for p in kb.style.banned_patterns:
        t = re.sub(p.pattern, lambda m: m.group(1) if m.lastindex and m.group(1) else "", t)
    for w in sorted((b.text for b in kb.style.banned if b.text != "您"), key=len, reverse=True):
        t = t.replace(w, "")
    # 清理删词留下的标点：连着的并成一个，句首的去掉，只剩标点的句子去掉
    t = re.sub(r"[，,、]\s*(?=[，,、。！？!?])", "", t)
    pieces = [re.sub(r"^[，,、\s]+", "", x) for x in re.split(r"(?<=[。！？!?\n])", t)]
    pieces = [x for x in pieces if re.search(r"[\u4e00-\u9fffA-Za-z0-9]", x)]
    out = "".join(pieces).strip()
    return re.sub(r"\n{3,}", "\n\n", out).strip() or "好的"


def segments(text: str, *, max_segments: int) -> list[str]:
    """按空行拆成几条（模型自己决定在哪断）；超过上限的并进最后一条。"""
    # 微信里句末一般不打句号（单个句号显得冷淡；新京报书评周刊《用不好的标点符号》2025-02-26），问号、感叹号留着
    parts = [p.strip().rstrip("。").strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]
    parts = [p for p in parts if p]
    if len(parts) <= max_segments:
        return parts
    head = parts[: max_segments - 1]
    return head + ["，".join(p.rstrip("。") for p in parts[max_segments - 1:])]


def soft_notes(parts: list[str], kb: ReceptionKB) -> list[str]:
    """不重写、只记一笔的（给后台看）：太长。"""
    notes = []
    long = [len(p) for p in parts if len(p) > kb.style.max_chars_per_msg]
    if long:
        notes.append(f"有 {len(long)} 条超过 {kb.style.max_chars_per_msg} 字")
    total = sum(len(p) for p in parts)
    if total > kb.style.max_chars_per_turn:
        notes.append(f"这一轮一共 {total} 字，偏长")
    return notes


def disclosed_recently(texts_and_reasons: list[tuple[str, list[str]]]) -> bool:
    """最近发过的话里有没有表明过身份：带 disclosure 标记，或同时有「AI」和「助手/生成」。"""
    for text, reasons in texts_and_reasons:
        if "disclosure" in (reasons or []):
            return True
        if re.search(r"AI|人工智能", text or "") and re.search(r"助手|生成|合成", text or ""):
            return True
    return False
