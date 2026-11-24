"""判断层：客人这几句话是哪一类（设计第四节）。

三步，照「先看事实、再让模型分」（小光第五轮第七节）和客服机器人通行的「先分类再分支」（Dify 问题分类节点、Rasa NLU）：
1. 平台事实先定：发了文件 → 发材料；带 PSY- 激活码 → 发激活码；不调模型。
2. 关键词定的几类（意图卡 decisive=true：被问是不是机器人、退款、发票、要找负责人）：命中就定，不等模型。
3. 其余交给模型分一次（一个小调用，只给意图目录和最近几句）；模型挂了或没配，用规则的打分兜底。

回复本来就要等几秒再发（第六节节奏），多这一次小调用客人感觉不到。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.intake.reception.kb import ReceptionKB

log = logging.getLogger("app.intake.reception")

PROMPT_FILE = Path(__file__).parent / "prompts" / "判断.md"
CODE_RE = re.compile(r"PSY[-－_ ]?[A-Z0-9]{9}", re.I)
_PUNCT = re.compile(r"[\s，。！？、,.!?~～…：:；;“”\"'（）()【】\[\]]+")
ANSWERABLE = re.compile(r"[？?]|吗|呀$|呢$|不$|哈$")


@dataclass
class Route:
    """这一轮的判断结果。intents 第一个是主的。"""

    intents: list[str]
    answering: bool = False  # 在回答助手上一问
    how: str = "rules"  # facts / keyword / model / rules
    scores: dict[str, float] = field(default_factory=dict)
    note: str = ""

    @property
    def main(self) -> str:
        return self.intents[0] if self.intents else "chitchat"


class IntentOut(BaseModel):
    """模型的判断：最多两类，第一个是主的。"""

    intents: list[str] = Field(description="这几句话属于哪一类（意图 id），最多两个，主要的放第一个")
    answering: bool = Field(default=False, description="客人是不是在回答助手上一句问的问题")


def _norm(t: str) -> str:
    return _PUNCT.sub("", (t or "").lower())


def _grams(t: str) -> set[str]:
    s = _norm(t)
    return set(s) | {s[i:i + 2] for i in range(len(s) - 1)}


_CN = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def _num(s: str) -> float:
    if s in _CN:
        return float(_CN[s])
    if len(s) == 2 and s[0] == "十" and s[1] in _CN:
        return 10.0 + _CN[s[1]]
    if len(s) == 2 and s[1] == "十" and s[0] in _CN:
        return 10.0 * _CN[s[0]]
    if len(s) == 3 and s[1] == "十" and s[0] in _CN and s[2] in _CN:
        return 10.0 * _CN[s[0]] + _CN[s[2]]
    try:
        return float(s)
    except ValueError:
        return 0.0


def minutes_said(text: str) -> int | None:
    """客人话里说的汇报时长（分钟），取最大的那个：90 分钟、一个半小时、两小时、一个多小时……没说返回 None。"""
    t = text or ""
    found: list[float] = []
    for m in re.finditer(r"(\d+(?:\.\d+)?|[一二两三四五六七八九十]{1,3})\s*(?:分钟|min|分(?!档))", t, flags=re.I):
        found.append(_num(m.group(1)))
    for m in re.finditer(r"(\d+(?:\.\d+)?|[一二两三四五六七八九十]{1,2})\s*个?\s*(半|多)?\s*(?:小时|钟头)", t):
        h = _num(m.group(1)) * 60 + (30 if m.group(2) == "半" else 10 if m.group(2) == "多" else 0)
        found.append(h)
    if re.search(r"(?<![一二两三四五六七八九十\d个])半(个)?小时", t):
        found.append(30)
    return int(max(found)) if found else None


def papers_said(text: str) -> int | None:
    found = [_num(m.group(1)) for m in re.finditer(r"(\d+|[一二两三四五六七八九十]{1,2})\s*篇", text or "")]
    return int(max(found)) if found else None


def over_limit(text: str, max_minutes: int, max_papers: int) -> str:
    """超出最长一档 / 最多篇数（Edison 11-19：一个半小时、8 篇这种直接转负责人，不报价不硬接）。没超返回空。"""
    out = []
    m, p = minutes_said(text), papers_said(text)
    if m is not None and max_minutes and m > max_minutes:
        out.append(f"讲 {m} 分钟，超过最长一档 {max_minutes} 分钟")
    if p is not None and max_papers and p > max_papers:
        out.append(f"{p} 篇，超过最多 {max_papers} 篇")
    return "；".join(out)


def similarity(a: str, b: str) -> float:
    """字 + 两字词的重合（Dice），0~1。短句够用，不用向量模型（不装大包）。"""
    ga, gb = _grams(a), _grams(b)
    if not ga or not gb:
        return 0.0
    return 2 * len(ga & gb) / (len(ga) + len(gb))


def _hits(card_keywords: list[str], text: str) -> int:
    n = 0
    for k in card_keywords:
        try:
            if re.search(k, text, flags=re.I):
                n += 1
        except re.error:
            continue
    return n


def score_rules(kb: ReceptionKB, text: str) -> dict[str, float]:
    """每一类的规则分：关键词每命中一个 +2，加上跟例句最像的那句的相似度 ×3。"""
    out: dict[str, float] = {}
    for c in kb.intents:
        kw = _hits(c.keywords, text)
        sim = max((similarity(text, e) for e in c.examples), default=0.0)
        out[c.id] = round(2 * kw + 3 * sim, 3)
    return out


def classify_rules(kb: ReceptionKB, texts: list[str], kinds: list[str], last_bot: str = "",
                   limits: tuple[int, int] | None = None) -> Route:
    """只用平台事实和规则判断（没模型时、测试、评测对照都用它）。limits=(最长分钟, 最多篇数)：超了直接算特殊情况。"""
    joined = "\n".join(t for t in texts if t)
    ids = {c.id for c in kb.intents}
    if limits and "special" in ids:
        why = over_limit(joined, *limits)
        if why:
            return Route(["special"], how="facts", note=f"超出档位：{why}")
    if any(k in ("file", "image") for k in kinds) and "send_material" in ids:
        return Route(["send_material"], how="facts", note="发了文件")
    if CODE_RE.search(joined) and "send_code" in ids:
        return Route(["send_code"], how="facts", note="带激活码")
    scores = score_rules(kb, joined)
    decisive = [c.id for c in kb.intents if c.decisive and c.id in scores and _hits(c.keywords, joined) > 0]
    if decisive:
        decisive.sort(key=lambda i: -scores[i])
        return Route(decisive[:2], how="keyword", scores=scores, note="关键词定的")
    asked = bool(last_bot) and bool(ANSWERABLE.search(last_bot.strip()[-12:] or ""))
    is_question = bool(re.search(r"[？?]|吗|么|能不能|可不可以|多少|怎么|几", joined))
    if asked and len(_norm(joined)) <= 12 and not is_question and "answer" in ids:
        return Route(["answer"], answering=True, how="rules", scores=scores, note="上一句问了，客人短答")
    if not asked:  # 「回答上一问」只在助手上一句真的问了东西时才成立
        scores = {k: v for k, v in scores.items() if k != "answer"}
    ranked = sorted(scores, key=lambda i: -scores[i])
    top = ranked[0] if ranked else "chitchat"
    if scores.get(top, 0) < 0.9:
        top = "chitchat" if "chitchat" in ids else top
        return Route([top], how="rules", scores=scores, note="都不像，按闲聊")
    second = ranked[1] if len(ranked) > 1 else None
    pick = [top] + ([second] if second and scores[second] >= 2 and scores[second] >= scores[top] * 0.75 else [])
    return Route(pick, how="rules", scores=scores)


def load_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8").strip()


def build_classifier(model: Any):
    from pydantic_ai import Agent

    return Agent(model, output_type=IntentOut, instructions=load_prompt(), retries=1)


def classifier_input(kb: ReceptionKB, *, stage: str, recent: list[tuple[str, str]], new: list[str], last_bot: str,
                     rules: Route) -> str:
    lines = ["【意图目录】", kb.catalog(), f"【现在这单在哪一步】{stage}"]
    if recent:
        lines.append("【前面几句】（旧→新）")
        lines += [f"{who}：{t[:120]}" for who, t in recent[-6:]]
    lines.append(f"【助手上一句】{last_bot[:160] or '（没有）'}")
    lines.append("【客人这次说的】")
    lines += [f"客人：{t[:300]}" for t in new]
    top = sorted(rules.scores, key=lambda i: -rules.scores[i])[:3] if rules.scores else rules.intents
    lines.append(f"【规则猜的】{'、'.join(top)}（只作参考）")
    return "\n".join(lines)


async def classify(kb: ReceptionKB, model: Any, *, texts: list[str], kinds: list[str], stage: str,
                   recent: list[tuple[str, str]], last_bot: str, limits: tuple[int, int] | None = None) -> Route:
    """完整的判断：事实 → 关键词 → 模型（没模型就规则兜底）。"""
    rules = classify_rules(kb, texts, kinds, last_bot, limits)
    if rules.how in ("facts", "keyword") or model is None:
        return rules
    try:
        agent = build_classifier(model)
        res = await agent.run(classifier_input(kb, stage=stage, recent=recent, new=texts, last_bot=last_bot, rules=rules))
        ids = {c.id for c in kb.intents}
        got = [i for i in res.output.intents if i in ids][:2]
        if not got:
            return Route(rules.intents, rules.answering, "rules", rules.scores, "模型给的类不认识，用规则的")
        return Route(got, bool(res.output.answering), "model", rules.scores)
    except Exception as e:  # 判断挂了不能挡住回复
        log.warning("意图判断失败，用规则的：%s", e)
        return Route(rules.intents, rules.answering, "rules", rules.scores, f"模型判断失败：{type(e).__name__}")
