"""入站分流的规则表（数据）：加载、校验、求值。entry.route 节点用。

规则表是 `app/channels/flows/<key>.json`，启动时 Pydantic 校验（写错了起不来）。按顺序取第一条条件全满足的规则。
条件只许用 `When` 里列的词（不执行代码）；去处只许用 `ACTIONS` 里的。换一张表就换一条路（比如免费领取流程）。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FLOW_DIR = Path(__file__).parent / "flows"

Action = Literal["claim", "welcome", "confirm", "confirm_on_platform", "serve", "file_refused", "visitor_qa",
                 "visitor_limited", "ignore"]
ACTIONS: tuple[str, ...] = Action.__args__  # type: ignore[attr-defined]


class When(BaseModel):
    """条件词表。没写的词不管；写了的全满足才算。"""

    model_config = ConfigDict(extra="forbid")

    kind_in: list[str] | None = None  # 消息类型：text / file / image / voice / video / enter / other
    entry_in: list[str] | None = None  # 哪个入口：entry.wecom / entry.webchat
    code: bool | None = None  # 消息里（或带码进入的 scene_param 里）认得出激活码
    code_new: bool | None = None  # 这枚码不是这个人在走那单已经用过的
    has_order: bool | None = None  # 这个人有在走的已认领单
    stage_in: list[str] | None = None  # 在走那单的状态
    confirm_said: bool | None = None  # 整条消息正好是确认说法（设置里的 confirm_phrases）
    self_confirm: bool | None = None  # 这单的渠道认客人自己确认（订单中枢的确认来源表 delivery.confirm_sources_by_platform）
    visitor_quota_left: bool | None = None  # 没认领的访客今天还有额度（会话、全站、同一 IP）


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=32, pattern=r"^[a-z_]+$")
    label: str = Field(min_length=1)
    when: When = Field(default_factory=When)
    go: Action


class RuleTable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    name: str
    description: str = ""
    rules: list[Rule] = Field(min_length=1)


class Facts(BaseModel):
    """entry.route 算好的事实，条件只看这些。"""

    kind: str
    entry: str
    code: str = ""
    code_new: bool = False
    has_order: bool = False
    stage: str = ""
    confirm_said: bool = False
    self_confirm: bool = False
    visitor_quota_left: bool = False


def _match(w: When, f: Facts) -> bool:
    checks = [
        w.kind_in is None or f.kind in w.kind_in,
        w.entry_in is None or f.entry in w.entry_in,
        w.code is None or bool(f.code) == w.code,
        w.code_new is None or f.code_new == w.code_new,
        w.has_order is None or f.has_order == w.has_order,
        w.stage_in is None or f.stage in w.stage_in,
        w.confirm_said is None or f.confirm_said == w.confirm_said,
        w.self_confirm is None or f.self_confirm == w.self_confirm,
        w.visitor_quota_left is None or f.visitor_quota_left == w.visitor_quota_left,
    ]
    return all(checks)


def pick(table: RuleTable, facts: Facts) -> Rule:
    for r in table.rules:
        if _match(r.when, facts):
            return r
    return Rule(id="none", label="没有规则满足", go="ignore")


@lru_cache(maxsize=16)
def load_table(key: str = "entry_default") -> RuleTable:
    path = FLOW_DIR / f"{key}.json"
    if not path.is_file():
        raise FileNotFoundError(f"没有规则表 {key}（{path}）")
    table = RuleTable.model_validate_json(path.read_text(encoding="utf-8"))
    if table.key != key:
        raise ValueError(f"规则表 {path.name} 里的 key 写的是 {table.key}，要和文件名一样")
    return table


def all_tables() -> list[RuleTable]:
    return [load_table(p.stem) for p in sorted(FLOW_DIR.glob("*.json"))]
