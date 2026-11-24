"""接待机器人的知识库（docs/任务单/12_接待机器人_设计.md 第三节）：意图卡、要问的几件事、说话规矩、节奏参数、表明身份的话。

默认值在同目录 kb_defaults.json，后台「设置 → 接待机器人」改了存 intake_kv 的 reception（照需求卡 brief 的做法）：
意图卡、要问的事、禁用说法整张替换（后台能删行），其余逐项盖。价格、时限、材料清单不在这里，
在业务设置（config_store）里，助手用工具算；这里只写「怎么认、回什么、引到哪」。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events import record_event
from app.intake.models import KV

SETTINGS_KEY = "reception"
DEFAULTS_FILE = Path(__file__).with_name("kb_defaults.json")
STAGES = ("售前", "认领", "收资料", "制作中", "交付后", "任何时候")
_WHOLE = ("intents", "asks", "samples")  # 整张替换的


class Disclosure(BaseModel):
    """表明身份（《人工智能生成合成内容标识办法》第四条第一项：文本起始处的文字提示；要同时有「AI」和「生成」）。
    Edison 11-19 定了一句（不要三选一）：「同学你好呀，这里是 PsyEngine，我是 AI 助手小鱼，下面的回复由 AI 生成，负责人随时看记录与接手」。"""

    text: str = Field(min_length=1)
    window_days: int = Field(default=7, ge=1, le=90)  # 多少天内说过一次就不再说
    web_footer: str = ""  # 网页聊天顶上一直挂着的一行（GB 45438 交互界面「持续显示」的写法）

    @field_validator("text")
    @classmethod
    def _has_ai(cls, v: str) -> str:
        if not (re.search(r"AI|人工智能", v) and re.search(r"生成|合成", v)):
            raise ValueError("表明身份的话要同时有「AI（或人工智能）」和「生成（或合成）」两样（GB 45438-2025 显式标识要素）")
        return v


class Sample(BaseModel):
    """一份样张（讲公开论文的免费稿，带水印的 PDF）：后台上传、可换；小鱼用 send_sample 发给客人。"""

    title: str = Field(min_length=1, max_length=60)
    about: str = ""  # 一句话：什么场合、哪本期刊、几页（小鱼挑哪份用）
    filename: str = ""
    storage_key: str = ""  # 平台存储里的位置（只给后端用，不出接口）
    size: int = 0

    @property
    def ready(self) -> bool:
        return bool(self.storage_key)


class Persona(BaseModel):
    """接待的人设（Edison 11-19 定：小鱼，公众号漫画里那个女生，学姐气质）。"""

    name: str = "小鱼"
    who: str = ""
    never: str = ""


class Owner(BaseModel):
    wechat: str = ""
    line: str = ""  # 转负责人时机器人照着说的那句（含微信号）
    mute_after_handoff: bool = True  # 转了以后机器人闭嘴，等负责人在后台点「交还机器人」


class Banned(BaseModel):
    text: str = Field(min_length=1)
    why: str = ""


class BannedPattern(BaseModel):
    pattern: str = Field(min_length=1)
    why: str = ""

    @field_validator("pattern")
    @classmethod
    def _compiles(cls, v: str) -> str:
        try:
            re.compile(v)
        except re.error as e:
            raise ValueError(f"正则「{v}」写错了：{e}") from e
        return v


class Style(BaseModel):
    max_chars_per_msg: int = Field(default=45, ge=10, le=500)
    max_chars_per_turn: int = Field(default=110, ge=20, le=2000)
    max_segments: dict[str, int] = Field(default_factory=lambda: {"web": 3, "wecom": 2})
    banned: list[Banned] = Field(default_factory=list)
    banned_patterns: list[BannedPattern] = Field(default_factory=list)
    fillers: list[str] = Field(default_factory=list)

    def segments_for(self, channel: str) -> int:
        return max(1, int(self.max_segments.get(channel, 2)))


class Rhythm(BaseModel):
    """像真人的回复节奏（设计第六节）。秒数都是「从客人最后一条消息算起」的。"""

    read_base_s: tuple[float, float] = (3, 9)
    read_per_char_s: float = Field(default=0.08, ge=0, le=2)
    read_max_s: float = Field(default=15, ge=0, le=120)
    typing_chars_per_s: float = Field(default=2.5, gt=0, le=50)
    typing_jitter: float = Field(default=0.3, ge=0, le=0.9)
    typing_min_s: float = Field(default=1.5, ge=0, le=60)
    typing_max_s: float = Field(default=15, ge=0, le=120)
    gap_s: tuple[float, float] = (0.6, 2.0)
    first_min_s: float = Field(default=4, ge=0, le=120)
    first_max_s: float = Field(default=40, ge=1, le=600)
    night_from: str = "00:30"
    night_to: str = "07:30"
    night_factor: float = Field(default=1.5, ge=1, le=5)
    night_max_s: float = Field(default=75, ge=1, le=900)
    filler_intents: list[str] = Field(default_factory=lambda: ["ask_progress", "revise"])
    filler_extra_s: tuple[float, float] = (6, 12)
    filler_every_hours: float = Field(default=2, ge=0, le=72)
    wecom_filler_min_sends_left: int = Field(default=4, ge=1, le=5)

    @field_validator("night_from", "night_to")
    @classmethod
    def _hhmm(cls, v: str) -> str:
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", v):
            raise ValueError("时间写成 HH:MM，如 00:30")
        return v


class Ask(BaseModel):
    """开工前要问的一件事（最小必问，设计第五节）。"""

    key: str
    label: str
    say: str = ""  # 怎么问（给模型参考，用自己的话说）
    markers: list[str] = Field(default_factory=list)  # 机器人的话里出现这些词就算问过
    max_times: int = Field(default=2, ge=1, le=10)  # 聊天里最多问几次，之后交给需求卡和提醒


class IntentCard(BaseModel):
    """一类客人会说的话：怎么认、回什么、引到哪、什么时候转负责人、几段示范。"""

    id: str = Field(pattern=r"^[a-z_]{2,32}$")
    name: str = Field(min_length=1, max_length=24)
    stage: str = "任何时候"
    desc: str = ""
    examples: list[str] = Field(default_factory=list)  # 客人会怎么说（判断用，也是测试句的来源）
    keywords: list[str] = Field(default_factory=list)  # 正则；命中给这一类加分
    decisive: bool = False  # 关键词命中就直接定（转负责人、合规这几类不等模型）
    reply: str = ""  # 回什么
    next: str = ""  # 回完引到哪
    handoff: str = ""  # 什么时候转负责人
    samples: list[str] = Field(default_factory=list)  # 示范对话（照负责人的口气）

    @field_validator("stage")
    @classmethod
    def _stage(cls, v: str) -> str:
        if v not in STAGES:
            raise ValueError(f"阶段只能是：{'、'.join(STAGES)}")
        return v

    @field_validator("keywords")
    @classmethod
    def _regex(cls, v: list[str]) -> list[str]:
        for k in v:
            try:
                re.compile(k)
            except re.error as e:
                raise ValueError(f"关键词正则「{k}」写错了：{e}") from e
        return v


class ReceptionKB(BaseModel):
    version: int = 1
    disclosure: Disclosure
    persona: Persona = Field(default_factory=Persona)
    owner: Owner = Field(default_factory=Owner)
    style: Style = Field(default_factory=Style)
    rhythm: Rhythm = Field(default_factory=Rhythm)
    asks: list[Ask] = Field(default_factory=list)
    intents: list[IntentCard] = Field(default_factory=list)
    samples: list[Sample] = Field(default_factory=list)  # 最多 3 份
    gzh_line: str = ""  # 想看样张时顺带说的那句（公众号每天的免费 PPT）

    @model_validator(mode="after")
    def _unique(self) -> ReceptionKB:
        ids = [c.id for c in self.intents]
        if len(ids) != len(set(ids)):
            raise ValueError("意图卡的 id 不能重复")
        if len(self.samples) > 3:
            raise ValueError("样张最多 3 份")
        for need in ("ask_bot", "escalate", "chitchat"):
            if need not in ids:
                raise ValueError(f"意图卡少了「{need}」（被问是不是机器人、要找负责人、闲聊这三类必须有）")
        return self

    def card(self, intent_id: str) -> IntentCard | None:
        return next((c for c in self.intents if c.id == intent_id), None)

    def ask(self, key: str) -> Ask | None:
        return next((a for a in self.asks if a.key == key), None)

    def catalog(self) -> str:
        """意图目录：一类一行（id、名字、一句话、两句例子），给判断用。"""
        return "\n".join(f"- {c.id}（{c.name}，{c.stage}）：{c.desc}。例：{'／'.join(c.examples[:3])}" for c in self.intents)


def defaults() -> dict[str, Any]:
    return json.loads(DEFAULTS_FILE.read_text(encoding="utf-8"))


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in over.items():
        if k in _WHOLE:
            out[k] = v
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v) if k != "style" else {**out[k], **v}
        else:
            out[k] = v
    return out


# 后台存一次知识库会把当时整张意图卡、要问的事都存进库（整张替换）；代码后来加的卡、改的默认原话就到不了线上。
# 存的版本比默认旧时：新加的卡、要问的事补进去（后台删掉的不会被这里加回来：只补这一版新加的）；
# 还是旧默认原话的几处换成新的（后台改过的不动）。
UPGRADES: dict[int, dict[str, Any]] = {
    2: {  # 11-19 资料清单：问要准备什么 → send_materials；场合先问；缺了点名要
        "add": {"intents": ["ask_materials"], "asks": ["occasion"]},
        "replace": [
            ("asks", "materials", "say", "材料直接发我就行，组会就发论文，开题就发开题报告"),
            ("intents", "send_code", "reply", "码由系统在你之前认领了，照【激活码】那一行说结果；认领上了按清单要资料。"),
            ("intents", "send_code", "samples", ["客人：PSY-XXXXXXXXX\n我：好嘞，对上了\n\n材料直接发我就行，组会就发论文"]),
            ("intents", "ask_buy", "reply", "还没发过就先 send_terms（会先发「做完你会拿到什么、几条先说清楚的」原文），他说可以再 send_payment"
                                            "（发付款链接）。你只说一两句，别复述，也别说「注意事项」「发卡站」这类词。"),
            ("intents", "send_material", "next", "缺什么问一件（材料 → 哪天汇报 → 时长）；资料齐了发需求卡链接请他点「对，开工」"),
        ],
    },
}
_ID = {"intents": "id", "asks": "key"}


def upgrade_stored(stored: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    have = int(stored.get("version") or 1)
    if not stored or have >= int(base.get("version") or 1):
        return stored
    out = dict(stored)
    for ver in sorted(v for v in UPGRADES if v > have):
        up = UPGRADES[ver]
        for table, ids in up.get("add", {}).items():
            if table not in out:
                continue
            rows = list(out[table])
            got = {r.get(_ID[table]) for r in rows}
            for i in ids:
                new = next((r for r in base.get(table, []) if r.get(_ID[table]) == i), None)
                if new is not None and i not in got:
                    rows.append(new)
            out[table] = rows
        for table, rid, field_name, old in up.get("replace", []):
            if table not in out:
                continue
            new = next((r for r in base.get(table, []) if r.get(_ID[table]) == rid), None)
            out[table] = [({**r, field_name: new[field_name]} if new is not None and r.get(_ID[table]) == rid
                           and r.get(field_name) == old else r) for r in out[table]]
    out["version"] = base.get("version", have)
    return out


def load(db: Session | None) -> ReceptionKB:
    stored: dict[str, Any] = {}
    if db is not None:
        row = db.get(KV, SETTINGS_KEY)
        stored = row.value if row is not None and isinstance(row.value, dict) else {}
    base = defaults()
    return ReceptionKB.model_validate(_merge(base, upgrade_stored(stored, base)))


def save(db: Session, kb: ReceptionKB, *, by: str = "edison") -> ReceptionKB:
    value = kb.model_dump(mode="json")
    row = db.get(KV, SETTINGS_KEY)
    if row is None:
        db.add(KV(key=SETTINGS_KEY, value=value, updated_at=utcnow()))
    else:
        row.value = value
        row.updated_at = utcnow()
    record_event(db, "intake.reception_kb_saved", "settings:reception", {"by": by, "intents": len(kb.intents)})
    db.flush()
    return kb
