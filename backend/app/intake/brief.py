"""需求卡（docs/任务单/09_需求引导_方案.md）：付了钱的研究生不知道怎么描述需求，就让他点选、看样张、传旧材料，
最后对着一张代码拼出来的「需求确认卡」点一次「对，开工」。没确认不开工。

- 题目、选项、默认值、样张都在设置里（默认值 brief_defaults.json，后台改了存 intake_kv 的 brief）；前端不写死选项文字
  （scripts/check.py 规矩 21）。
- 确认卡由这里的代码按模板拼，这条链路不调模型（同上）。
- 「没确认不开工」靠流程里的闸口节点 gate.brief_confirmed（intake/flows/paid_custom.json：收资料 → 需求卡确认了没有 →
  开工判断 → 制作中）。这里不写 flow_step / stage，确认了只发事件 brief_confirmed，由引擎往下走。
- 客人确认 = 他点「对，开工」；客人在聊天里口头说「可以」，负责人在后台代确认，留痕写明是代确认、依据是什么。
- 确认了就把场合、语言、时长写回订单事实（客人明确选的直接写；「按推荐」的只填空着的），清单少问一句。
- 确认卡并进开单说明里已有的「偏好」那一段（handoff.render_requirements），给做 PPT 的人看，不另起一份。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events import list_events, record_event
from app.intake import clock
from app.intake.config_store import BizConfig, load_config
from app.intake.models import KV, Brief, FileRecord, Order

SETTINGS_KEY = "brief"
DEFAULTS_FILE = Path(__file__).with_name("brief_defaults.json")
DEFAULT_CHOICE = "__default__"  # 「不知道，按推荐做」
NONE_STYLE = "__none__"  # 样张「都不像」
EDITABLE_STAGES = ("paid", "claimed", "collecting")  # 开工之前能改、能确认
FILE_NOTE = "需求卡"
NOTE_MAX = 200
KIND_PURPOSE = {"ref": "参考", "template": "模板"}


# ---------------------------------------------------------------- 设置

class BriefOption(BaseModel):
    key: str = Field(min_length=1, max_length=24, pattern=r"^[a-z0-9_]+$")
    label: str = Field(min_length=1, max_length=24)
    example: str = Field(default="", max_length=60)
    fact: str = Field(default="", max_length=16, description="确认后写回订单的值（场合、语言）")
    upload: bool = Field(default=False, description="选了它要传文件（有模板）")


class BriefQuestion(BaseModel):
    key: str = Field(min_length=1, max_length=24, pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1, max_length=30)
    hint: str = Field(default="", max_length=60)
    kind: Literal["single", "multi", "minutes"] = "single"
    fact: Literal["", "occasion", "language"] = ""
    optional: bool = False
    allow_note: bool = False
    note_placeholder: str = Field(default="", max_length=60)
    default: str | list[str] = ""
    options: list[BriefOption] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> BriefQuestion:
        keys = [o.key for o in self.options]
        if len(keys) != len(set(keys)):
            raise ValueError(f"「{self.title}」的选项代号重复了")
        if self.kind == "minutes":
            if not (self.default == "tier_max" or (isinstance(self.default, str) and self.default.isdigit())):
                raise ValueError(f"「{self.title}」的默认值写 tier_max（档位上限）或分钟数")
            return self
        if not self.options:
            raise ValueError(f"「{self.title}」至少要有一个选项")
        if self.kind == "single":
            if not isinstance(self.default, str) or self.default not in keys:
                raise ValueError(f"「{self.title}」的推荐值要是其中一个选项（现在是 {self.default!r}）")
        else:
            d = self.default if isinstance(self.default, list) else [self.default] if self.default else []
            bad = [x for x in d if x not in keys]
            if bad:
                raise ValueError(f"「{self.title}」的推荐值里有不存在的选项：{'、'.join(bad)}")
            self.default = d
        return self

    def option(self, key: str) -> BriefOption | None:
        return next((o for o in self.options if o.key == key), None)


class BriefSample(BaseModel):
    key: str = Field(min_length=1, max_length=24, pattern=r"^[a-z0-9_]+$")
    title: str = Field(min_length=1, max_length=24)
    note: str = Field(default="", max_length=60)
    image: str = Field(default="", max_length=300, description="缩略图地址（/site-assets/… 或 https://…）")
    source: str = Field(default="", max_length=120, description="讲的是哪篇公开论文")

    @field_validator("image")
    @classmethod
    def _image(cls, v: str) -> str:
        v = v.strip()
        if v and not (v.startswith("/") or v.startswith("https://")):
            raise ValueError("样张图片地址要以 / 或 https:// 开头")
        return v


class BriefStyle(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    hint: str = Field(default="", max_length=60)
    none_label: str = Field(default="都不像", min_length=1, max_length=12)
    none_placeholder: str = Field(default="", max_length=60)
    default: str = Field(default="", description="按推荐时算哪份；空 = 你们定")
    default_text: str = Field(default="你们定", max_length=16)
    samples: list[BriefSample] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def _check(self) -> BriefStyle:
        keys = [s.key for s in self.samples]
        if len(keys) != len(set(keys)):
            raise ValueError("样张代号重复了")
        if self.default and self.default not in keys:
            raise ValueError("样张的推荐值要是其中一份")
        return self

    def sample(self, key: str) -> BriefSample | None:
        return next((s for s in self.samples if s.key == key), None)


class BriefRefs(BaseModel):
    title: str = Field(min_length=1, max_length=40)
    hint: str = Field(default="", max_length=100)
    max_files: int = Field(default=8, ge=0, le=20)


class BriefSettings(BaseModel):
    remind_after_hours: int = Field(default=2, ge=0, le=72, description="认领后（或发回重确认后）几小时没确认提醒一次；0 = 不提醒")
    minutes_step: int = Field(default=5, ge=1, le=30)
    minutes_floor: int = Field(default=5, ge=1, le=60)
    questions: list[BriefQuestion]
    style: BriefStyle
    refs: BriefRefs
    texts: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> BriefSettings:
        keys = [q.key for q in self.questions]
        if len(keys) != len(set(keys)):
            raise ValueError("题目代号重复了")
        if "style" in keys or "refs" in keys:
            raise ValueError("题目代号不能叫 style、refs（样张、旧材料用了）")
        if sum(1 for q in self.questions if q.kind == "minutes") > 1:
            raise ValueError("「讲多久」只能有一题")
        return self

    def question(self, key: str) -> BriefQuestion | None:
        return next((q for q in self.questions if q.key == key), None)

    def text(self, key: str) -> str:
        return self.texts.get(key) or _defaults()["texts"].get(key, "")


@lru_cache(maxsize=1)
def _defaults_raw() -> str:
    return DEFAULTS_FILE.read_text(encoding="utf-8")


def _defaults() -> dict[str, Any]:
    data = json.loads(_defaults_raw())
    data.pop("_说明", None)
    return data


def load_settings(db: Session) -> BriefSettings:
    """默认值（brief_defaults.json）上盖库里存的：题目、样张、旧材料整段替换（后台能删行），话术逐条盖。"""
    data = _defaults()
    row = db.get(KV, SETTINGS_KEY)
    stored = row.value if row is not None and isinstance(row.value, dict) else {}
    for k, v in stored.items():
        if k == "texts" and isinstance(v, dict):
            data["texts"] = {**data["texts"], **{a: b for a, b in v.items() if isinstance(b, str) and b.strip()}}
        elif k in BriefSettings.model_fields:
            data[k] = v
    try:
        return BriefSettings.model_validate(data)
    except ValueError:
        return BriefSettings.model_validate(_defaults())  # 存坏了也不能把客人挡住：退回默认


def save_settings(db: Session, s: BriefSettings, *, by: str = "edison") -> BriefSettings:
    row = db.get(KV, SETTINGS_KEY)
    value = s.model_dump()
    if row is None:
        db.add(KV(key=SETTINGS_KEY, value=value, updated_at=utcnow()))
    else:
        row.value = value
        row.updated_at = utcnow()
    record_event(db, "intake.brief_settings_changed", "", {"by": by, "questions": [q.key for q in s.questions],
                                                           "samples": [x.key for x in s.style.samples]})
    db.flush()
    return s


# ---------------------------------------------------------------- 一单的需求卡

def get(db: Session, order: Order) -> Brief | None:
    return db.scalar(select(Brief).where(Brief.order_id == order.id))


def ensure(db: Session, order: Order) -> Brief:
    b = get(db, order)
    if b is None:
        now = utcnow()
        b = Brief(order_id=order.id, answers={}, version=0, remind_from=order.claimed_at or now, created_at=now, updated_at=now)
        db.add(b)
        db.flush()
    return b


def is_confirmed(b: Brief | None) -> bool:
    return b is not None and b.confirmed_at is not None and b.confirmed_version == b.version


def confirmed(db: Session, order: Order) -> bool:
    return is_confirmed(get(db, order))


# 客人本人勾的同意（协议和隐私、材料交给 AI 处理含境外、定制不退）记在事件 website.consent 上：
# 自有网页单下单时勾（付款建单后抄到订单上），小红书、闲鱼这类平台单在确认卡点「对，开工」前勾。
# 出境要本人「单独同意」（个人信息保护法第三十九条）：负责人代确认需求卡可以，代勾同意不行（admin/brief_router.py 拦）
CONSENT_EVENT = "website.consent"


def has_consent(db: Session, order: Order) -> bool:
    return bool(list_events(db, subject=f"order:{order.id}", type=CONSENT_EVENT, limit=1))


def editable(order: Order) -> bool:
    return order.stage in EDITABLE_STAGES and not order.voided_at and not order.started_at


def minutes_range(s: BriefSettings, cfg: BizConfig, order: Order) -> tuple[int, int]:
    """能选的分钟数：下限是设置里的最小值，上限是这单时长档的上限（不能超出档位）。"""
    t = cfg.tier(order.tier_key)
    high = t.max_minutes if t is not None else 60
    return min(s.minutes_floor, high), high


def default_minutes(q: BriefQuestion, s: BriefSettings, cfg: BizConfig, order: Order) -> int:
    low, high = minutes_range(s, cfg, order)
    if isinstance(q.default, str) and q.default.isdigit():
        return max(low, min(high, int(q.default)))
    return high


def minutes_options(s: BriefSettings, cfg: BizConfig, order: Order) -> list[int]:
    low, high = minutes_range(s, cfg, order)
    step = s.minutes_step
    first = ((low + step - 1) // step) * step
    out = list(range(first, high + 1, step))
    if not out or out[-1] != high:
        out.append(high)
    if low not in out and low < first:
        out.insert(0, low)
    return out


def _choice(answers: dict[str, Any], key: str) -> tuple[Any, str]:
    a = answers.get(key) or {}
    if not isinstance(a, dict):
        return None, ""
    return a.get("choice"), str(a.get("note") or "")


def clean_answers(s: BriefSettings, cfg: BizConfig, order: Order, raw: dict[str, Any]) -> dict[str, Any]:
    """只留认得的题目和选项；分钟数不许超出档位；一句话截到 200 字。认不出的抛 ValueError（接口 400）。"""
    out: dict[str, Any] = {}
    for key, val in (raw or {}).items():
        if not isinstance(val, dict):
            continue
        choice, note = val.get("choice"), str(val.get("note") or "").strip()[:NOTE_MAX]
        if key == "style":
            if choice not in (None, "", DEFAULT_CHOICE, NONE_STYLE) and s.style.sample(str(choice)) is None:
                raise ValueError("没有这份样张")
            out[key] = {"choice": choice or "", "note": note if choice == NONE_STYLE else ""}
            continue
        q = s.question(key)
        if q is None:
            continue
        if choice in (None, ""):
            out[key] = {"choice": [] if q.kind == "multi" else "", "note": note if q.allow_note else ""}
            continue
        if choice == DEFAULT_CHOICE or choice == [DEFAULT_CHOICE]:
            out[key] = {"choice": DEFAULT_CHOICE, "note": note if q.allow_note else ""}
            continue
        if q.kind == "minutes":
            try:
                n = int(choice)
            except (TypeError, ValueError):
                raise ValueError("讲多久要写分钟数") from None
            low, high = minutes_range(s, cfg, order)
            if n > high:
                t = cfg.tier(order.tier_key)
                raise ValueError(f"你买的是{t.name if t else ''}档，最多 {high} 分钟；要更长得补差价，在聊天里跟助手说")
            if n < low:
                raise ValueError(f"最少 {low} 分钟")
            out[key] = {"choice": str(n), "note": ""}
        elif q.kind == "multi":
            picks = choice if isinstance(choice, list) else [choice]
            picks = [str(p) for p in picks if p != DEFAULT_CHOICE]
            bad = [p for p in picks if q.option(p) is None]
            if bad:
                raise ValueError(f"「{q.title}」里没有这个选项")
            out[key] = {"choice": list(dict.fromkeys(picks)), "note": note if q.allow_note else ""}
        else:
            if q.option(str(choice)) is None:
                raise ValueError(f"「{q.title}」里没有这个选项")
            out[key] = {"choice": str(choice), "note": note if q.allow_note else ""}
    return out


class CardLine(BaseModel):
    key: str
    label: str
    value: str
    by_default: bool = False
    missing: bool = False


def _q_label(q: BriefQuestion) -> str:
    return {"occasion": "场合", "audience": "听众", "minutes": "时长", "language": "语言", "template": "模板",
            "focus": "重点", "avoid": "不要"}.get(q.key, q.title)


def card_lines(db: Session, order: Order, *, s: BriefSettings | None = None, cfg: BizConfig | None = None,
               answers: dict[str, Any] | None = None) -> list[CardLine]:
    """需求确认卡：按设置里的题目顺序，一题一行；「按推荐」的写明是推荐值。纯代码拼，不调模型。"""
    s = s or load_settings(db)
    cfg = cfg or load_config(db)
    if answers is None:
        b = get(db, order)
        answers = b.answers if b is not None else {}
    tag = s.text("default_tag")
    files = brief_files(db, order)
    lines: list[CardLine] = []
    for q in s.questions:
        choice, note = _choice(answers, q.key)
        label = _q_label(q)
        if q.kind == "minutes":
            t = cfg.tier(order.tier_key)
            if choice == DEFAULT_CHOICE:
                n = default_minutes(q, s, cfg, order)
                tail = f"{t.name}档上限" if t is not None and n == (t.max_minutes if t else 0) else ""
                lines.append(CardLine(key=q.key, label=label, value=f"{n} 分钟（{tag}" + (f"：{tail}" if tail else "") + "）",
                                      by_default=True))
            elif choice:
                lines.append(CardLine(key=q.key, label=label, value=f"{choice} 分钟"))
            else:
                lines.append(CardLine(key=q.key, label=label, value="还没选", missing=True))
            continue
        if q.kind == "multi":
            if choice == DEFAULT_CHOICE:
                names = [q.option(k).label for k in (q.default or []) if q.option(k)]
                value = ("、".join(names) if names else s.style.default_text) + f"（{tag}）"
                lines.append(CardLine(key=q.key, label=label, value=value + (f"；补充：{note}" if note else ""), by_default=True))
                continue
            picks = [q.option(k).label for k in (choice or []) if q.option(k)]
            if not picks and not note:
                if not q.optional:
                    lines.append(CardLine(key=q.key, label=label, value="还没选", missing=True))
                continue
            value = "、".join(picks) if picks else ""
            value = f"{value}；补充：{note}" if value and note else (value or f"补充：{note}")
            lines.append(CardLine(key=q.key, label=label, value=value))
            continue
        by_default = choice == DEFAULT_CHOICE
        opt = q.option(str(q.default)) if by_default else (q.option(str(choice)) if choice else None)
        if opt is None:
            if not q.optional:
                lines.append(CardLine(key=q.key, label=label, value="还没选", missing=True))
            continue
        value = opt.label + (f"（{tag}）" if by_default else "")
        if opt.upload:
            tpl = [f for f in files if f.purpose == KIND_PURPOSE["template"]]
            value += f"，传了 {len(tpl)} 份：{'、'.join(f.filename for f in tpl)}" if tpl else "，还没传上来（在聊天里发也行）"
        lines.append(CardLine(key=q.key, label=label, value=value, by_default=by_default))
    # 样张
    choice, note = _choice(answers, "style")
    if s.style.samples:
        if choice == NONE_STYLE:
            lines.append(CardLine(key="style", label="风格", value=f"{s.style.none_label}" + (f"：{note}" if note else "")))
        elif choice == DEFAULT_CHOICE or not choice:
            smp = s.style.sample(s.style.default) if s.style.default else None
            value = (f"最像「{smp.title}」" if smp else s.style.default_text) + f"（{tag}）"
            lines.append(CardLine(key="style", label="风格", value=value, by_default=True, missing=False))
        else:
            smp = s.style.sample(str(choice))
            lines.append(CardLine(key="style", label="风格", value=f"最像「{smp.title}」" if smp else s.style.default_text))
    refs = [f for f in files if f.purpose == KIND_PURPOSE["ref"]]
    lines.append(CardLine(key="refs", label="参考材料",
                          value=f"{len(refs)} 份（{'、'.join(f.filename for f in refs[:4])}{'等' if len(refs) > 4 else ''}）" if refs else "没传"))
    return lines


def card_text(lines: list[CardLine]) -> str:
    return "\n".join(f"{x.label}：{x.value}" for x in lines)


def missing(lines: list[CardLine]) -> list[str]:
    return [x.label for x in lines if x.missing]


# ---------------------------------------------------------------- 动作

def _touch(b: Brief, by: str) -> None:
    b.updated_by = by
    b.updated_at = utcnow()


def save(db: Session, ctx: Any, order: Order, raw: dict[str, Any], *, by: str = "customer",
         merge: bool = True) -> Brief:
    """存客人（或负责人）点的选项。开工以后不能改（有变化在聊天里跟助手说）。确认过又改了 → 要重新确认。"""
    if not editable(order):
        raise ValueError("已经开工了，需求卡不能再改；有变化在聊天里跟助手说")
    s, cfg = load_settings(db), load_config(db)
    b = ensure(db, order)
    clean = clean_answers(s, cfg, order, raw)
    new = {**(b.answers or {}), **clean} if merge else clean
    if new == (b.answers or {}):
        return b
    was = is_confirmed(b)
    b.answers = new
    b.version = (b.version or 0) + 1
    _touch(b, by)
    if was:  # 确认过又改了：从现在起算提醒
        b.remind_from = utcnow()
        b.reminded_at = None
    record_event(db, "intake.brief_saved", f"order:{order.id}", {"by": by, "version": b.version, "keys": sorted(clean),
                                                               "was_confirmed": was})
    return b


def confirm(db: Session, ctx: Any, order: Order, *, method: Literal["customer", "proxy"], by: str, note: str = "",
            version: int | None = None) -> Brief:
    """「对，开工」（method=customer）或负责人代确认（method=proxy，要写依据）。确认了把事实写回订单，再发 brief_confirmed。"""
    from app.intake import flow, service  # service import 了本文件（开工判断看需求卡），这里晚一点 import

    if not editable(order):
        raise ValueError("这单现在不在收资料，不用确认需求卡")
    note = (note or "").strip()[:256]
    if method == "proxy" and not note:
        raise ValueError("代确认要写一句依据，比如「客人在聊天里说可以」")
    b = ensure(db, order)
    if version is not None and version != (b.version or 0):
        raise ValueError("需求卡刚改过，再看一眼确认卡")
    s, cfg = load_settings(db), load_config(db)
    if method == "proxy":  # 代确认 = 照确认卡上现在的样子认；没选的题按推荐（卡上写明「按推荐」）
        blanks = {q.key: {"choice": DEFAULT_CHOICE} for q in s.questions
                  if not q.optional and not _choice(b.answers or {}, q.key)[0]}
        if blanks:
            b.answers = {**(b.answers or {}), **blanks}
            b.version = (b.version or 0) + 1
    lines = card_lines(db, order, s=s, cfg=cfg, answers=b.answers or {})
    gaps = missing(lines)
    if gaps:
        raise ValueError("还有没选的：" + "、".join(gaps))
    now = utcnow()
    b.confirmed_at = now
    b.confirmed_version = b.version or 0
    b.confirm_method = method
    b.confirmed_by = by
    b.confirm_note = note if method == "proxy" else ""
    b.card_text = card_text(lines)
    _touch(b, by)
    record_event(db, "intake.brief_confirmed", f"order:{order.id}", {
        "by": by, "method": method, "note": b.confirm_note, "version": b.confirmed_version, "card": b.card_text[:1500]})
    changes = facts_from(s, cfg, order, b.answers or {})
    if changes:
        service.update_order(db, ctx, order, changes, by="brief")
    flow.emit(db, ctx, order, "brief_confirmed", by=by, why="需求卡确认了" + ("（负责人代确认）" if method == "proxy" else ""))
    return b


def facts_from(s: BriefSettings, cfg: BizConfig, order: Order, answers: dict[str, Any]) -> dict[str, Any]:
    """确认卡 → 订单事实：客人明确选的直接写；「按推荐」的只填空着的（不盖助手或负责人记过的）。"""
    out: dict[str, Any] = {}
    for q in s.questions:
        choice, _ = _choice(answers, q.key)
        if not choice:
            continue
        default = choice == DEFAULT_CHOICE
        if q.kind == "minutes":
            n = default_minutes(q, s, cfg, order) if default else int(choice)
            if not default or order.duration_min is None:
                out.update(duration_min=n, duration_default=default, duration_confirmed=True)
            elif order.duration_default and not order.duration_confirmed:
                out.update(duration_confirmed=True)
            continue
        if not q.fact or q.kind != "single":
            continue
        opt = q.option(str(q.default) if default else str(choice))
        if opt is None or not opt.fact:
            continue
        if q.fact == "occasion" and opt.fact not in cfg.occasions:
            continue
        current = getattr(order, q.fact) or ""
        if (not default or not current) and current != opt.fact:
            out[q.fact] = opt.fact
    return out


def send_back(db: Session, ctx: Any, order: Order, raw: dict[str, Any], *, note: str, by: str = "edison") -> Brief:
    """负责人改了需求卡再发给客人重新确认（发话由调用方走入口发；这里只记账、重新起算提醒）。"""
    b = save(db, ctx, order, raw, by=by)
    if is_confirmed(b):  # 没改出不同：也要客人再点一次
        b.version = (b.version or 0) + 1
    now = utcnow()
    b.sent_back_at = now
    b.sent_back_note = (note or "").strip()[:256]
    b.remind_from = now
    b.reminded_at = None
    _touch(b, by)
    record_event(db, "intake.brief_sent_back", f"order:{order.id}", {"by": by, "version": b.version, "note": b.sent_back_note})
    return b


def brief_files(db: Session, order: Order) -> list[FileRecord]:
    return list(db.scalars(select(FileRecord).where(
        FileRecord.order_id == order.id, FileRecord.role == "material", FileRecord.note == FILE_NOTE).order_by(FileRecord.id)))


def add_file(db: Session, ctx: Any, order: Order, *, filename: str, data: bytes, content_type: str = "",
             kind: Literal["ref", "template"]) -> FileRecord:
    """需求卡里传的旧材料（参考）和模板：收进这单的资料，用途标「参考」/「模板」，跟必交资料分开。"""
    if not editable(order):
        raise ValueError("已经开工了，补充的材料在聊天里发给助手")
    s = load_settings(db)
    have = brief_files(db, order)
    if kind == "ref" and len([f for f in have if f.purpose == KIND_PURPOSE["ref"]]) >= s.refs.max_files:
        raise ValueError(f"参考材料最多 {s.refs.max_files} 份")
    key = ctx.storage.save(data, folder=f"intake/{order.customer_id or 0}", filename=filename)
    rec = FileRecord(customer_id=order.customer_id or 0, order_id=order.id, role="material", filename=filename[:256],
                     size=len(data), content_type=content_type[:128], storage_key=key, purpose=KIND_PURPOSE[kind],
                     note=FILE_NOTE, created_at=utcnow())
    db.add(rec)
    db.flush()
    record_event(db, "intake.brief_file", f"order:{order.id}", {"file": rec.id, "name": rec.filename, "kind": kind, "size": len(data)})
    if kind == "template":
        from app.intake import service

        service.refresh_status(db, ctx, order)  # 模板也是清单上的一项
    return rec


def remove_file(db: Session, ctx: Any, order: Order, file_id: int) -> None:
    if not editable(order):
        raise ValueError("已经开工了，不能删")
    f = db.get(FileRecord, file_id)
    if f is None or f.order_id != order.id or f.note != FILE_NOTE:
        raise LookupError("没有这个文件")
    key = f.storage_key
    db.delete(f)
    db.flush()
    ctx.storage.delete(key)
    record_event(db, "intake.brief_file_removed", f"order:{order.id}", {"file": file_id})


# ---------------------------------------------------------------- 给别处看的

def brief_path(order: Order) -> str:
    return f"/b/{order.delivery_token}"


def brief_url(ctx: Any, order: Order) -> str:
    base = getattr(ctx, "public_base_url", "") or ""
    return f"{base.rstrip('/')}{brief_path(order)}"


def method_text(b: Brief) -> str:
    if b.confirm_method == "proxy":
        return "负责人代确认" + (f"（依据：{b.confirm_note}）" if b.confirm_note else "")
    return "客人自己点了「对，开工」"


def handoff_text(db: Session, order: Order) -> str:
    """开单说明里「客人的需求和偏好」那一段用：确认卡全文 + 谁什么时候确认的。没确认（老单、代开工）就空。"""
    b = get(db, order)
    if not is_confirmed(b):
        return ""
    when = clock.local_now(b.confirmed_at).strftime("%m-%d %H:%M")
    return f"需求确认卡（{when} {method_text(b)}）：\n{b.card_text}"


def condition(db: Session, order: Order) -> tuple[bool, str]:
    """后台订单卡「开工条件」那一行、助手的情况里用。"""
    b = get(db, order)
    if is_confirmed(b):
        return True, method_text(b)
    if b is not None and b.confirmed_at is not None:
        return False, "确认过以后又改了，等客人再点「对，开工」"
    if b is not None and b.sent_back_at is not None:
        return False, "负责人改了发回去了，等客人再确认"
    if b is not None and b.answers:
        return False, "客人选了一部分，还没点「对，开工」"
    return False, "客人还没填需求卡"


def bot_line(db: Session, ctx: Any, order: Order) -> str:
    """助手的情况里加一行（助手不收需求卡，只提醒客人去点、去确认）。"""
    if not editable(order):
        return ""
    ok, detail = condition(db, order)
    if ok:
        return f"【需求卡】确认了（{detail}）"
    return (f"【需求卡】没确认：{detail}。需求卡由表单收，不用你问场合听众风格这些；客人没点的，把链接发给他请他点一下「对，开工」："
            f"{brief_url(ctx, order)}。客人在聊天里说「可以」也要请他点按钮，点不了就说会请负责人代确认（send_owner_wechat）。没确认不开工。")


def due_reminders(db: Session, now: datetime | None = None, *, limit: int = 50) -> list[Order]:
    """认领（或发回、确认后又改）后多久没确认、还没提醒过的单（提醒一次，不自动开工）。"""
    s = load_settings(db)
    if s.remind_after_hours <= 0:
        return []
    now = now or utcnow()
    cut = now - timedelta(hours=s.remind_after_hours)
    rows = list(db.scalars(select(Order).where(
        Order.stage.in_(("claimed", "collecting")), Order.voided_at.is_(None), Order.started_at.is_(None),
        Order.claimed_at.is_not(None), Order.claimed_at <= cut, Order.customer_id.is_not(None)).order_by(Order.id).limit(500)))
    out: list[Order] = []
    for o in rows:
        b = get(db, o)
        if is_confirmed(b):
            continue
        start = (b.remind_from if b is not None and b.remind_from else o.claimed_at)
        if start is None or start > cut:
            continue
        if b is not None and b.reminded_at is not None and b.reminded_at >= start:
            continue
        out.append(o)
        if len(out) >= limit:
            break
    return out


def mark_reminded(db: Session, order: Order, *, now: datetime | None = None) -> None:
    b = ensure(db, order)
    b.reminded_at = now or utcnow()
    record_event(db, "intake.brief_reminded", f"order:{order.id}", {"version": b.version})


# ---------------------------------------------------------------- 页面要的整张

def view(db: Session, ctx: Any, order: Order) -> dict[str, Any]:
    """客人页面、后台都用这一份：设置里的题目和选项、点过的、确认卡、确认了没有、谁确认的。"""
    from app.intake import pricing

    s, cfg = load_settings(db), load_config(db)
    b = get(db, order)
    answers = b.answers if b is not None else {}
    low, high = minutes_range(s, cfg, order)
    t = cfg.tier(order.tier_key)
    lines = card_lines(db, order, s=s, cfg=cfg, answers=answers)
    q_min = next((q for q in s.questions if q.kind == "minutes"), None)
    if not editable(order):
        state = "confirmed" if is_confirmed(b) else "locked"
    elif is_confirmed(b):
        state = "confirmed"
    elif b is not None and b.sent_back_at is not None and (b.confirmed_at is None or b.sent_back_at > b.confirmed_at):
        state = "sent_back"
    else:
        state = "open"
    return {
        "order_no": f"{order.id:05d}",
        "sku_name": pricing.sku_name(cfg, order.sku, [a.get("key", "") for a in (order.addons or []) if a.get("by") == "bundle"]) if order.sku else "",
        "tier_name": t.name if t is not None else "",
        "minutes": {"low": low, "high": high, "options": minutes_options(s, cfg, order),
                    "default": default_minutes(q_min, s, cfg, order) if q_min else high},
        "settings": {"questions": [q.model_dump() for q in s.questions], "style": s.style.model_dump(),
                     "refs": s.refs.model_dump(), "texts": {k: s.text(k) for k in _defaults()["texts"]}},
        "answers": answers,
        "version": b.version if b is not None else 0,
        "files": [{"id": f.id, "name": f.filename, "size": f.size, "kind": "template" if f.purpose == KIND_PURPOSE["template"] else "ref"}
                  for f in brief_files(db, order)],
        "card": [x.model_dump() for x in lines],
        "missing": missing(lines),
        "state": state,
        "editable": editable(order),
        "confirmed_at": b.confirmed_at if is_confirmed(b) else None,
        "confirm_method": b.confirm_method if is_confirmed(b) else "",
        "confirm_note": b.confirm_note if is_confirmed(b) else "",
        "sent_back_note": b.sent_back_note if state == "sent_back" else "",
        "stage": order.stage,
        "consent_needed": not has_consent(db, order),  # 确认卡上要不要放三项勾选（还没勾过的单）
        "revisions_included": cfg.revisions_included,  # 勾选里「不满意可以改几轮」
    }
