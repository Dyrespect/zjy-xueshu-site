"""节点注册表（顶层设计第十八节「节点化架构」）：每个能力是一个节点，带一张说明卡，登记在这里。

- 说明卡 NodeCard 缺一项就注册不了（Pydantic 校验；scripts/check.py 也静态拦）。
- 节点之间不互相 import，要用别的节点就 `run_node("节点 id", call, 输入)`。
- 节点文件放 `app/<模块>/nodes/<id 把点换成下划线>.py`，文件末尾 `register(CARD, handler)`；
  启动时 app/registry.py 的 import_all_nodes() 把每个业务模块的 nodes/ 导入一遍。
- 这里是底座：不 import 任何业务模块。流程（节点怎么连）在 app/intake/flow.py。
说明卡格式、跨模块怎么调：docs/任务单/06_订单中枢契约.md 第四节。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

CATEGORIES = ("触发", "渠道", "入口", "订单", "关口", "对话", "制作", "交付", "财务", "运营", "获客")
STATUSES = ("已有", "要改", "要新做")


class NodeExit(BaseModel):
    key: str = Field(min_length=1, max_length=32, pattern=r"^[a-z_]+$")
    label: str = Field(min_length=1)
    kind: Literal["ok", "fail", "wait"]


class NodeCard(BaseModel):
    """一个节点的说明卡（机器可读）。字段含义见契约第四节第 1 条。"""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    id: str = Field(pattern=r"^[a-z]+(\.[a-z_]+)+$")
    name: str = Field(min_length=2)
    description: str = Field(min_length=10)
    category: Literal["触发", "渠道", "入口", "订单", "关口", "对话", "制作", "交付", "财务", "运营", "获客"]
    tech: list[str] = Field(min_length=1)
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    exits: list[NodeExit] = Field(min_length=1)
    config: list[str] = Field(min_length=1)  # 用到的设置字段「字段名：说明」；没有写「无」
    emits: list[str] = Field(min_length=1)  # 发出的事件；没有写「无」
    listens: list[str] = Field(min_length=1)  # 订阅的事件；没有写「无」
    replaceable: list[str] = Field(min_length=1)  # 同一位置还能换成什么；没有写「暂无」
    failure: str = Field(min_length=6)  # 失败怎么处理、能不能重试、幂等怎么保证
    owner: str = Field(min_length=1)  # 归哪个模块（A–L）
    status: Literal["已有", "要改", "要新做"]

    @field_validator("tech", "config", "emits", "listens", "replaceable")
    @classmethod
    def _no_blank(cls, v: list[str]) -> list[str]:
        if any(not str(x).strip() for x in v):
            raise ValueError("不能有空字符串；真没有就写「无」或「暂无」")
        return v

    @field_validator("input_model", "output_model")
    @classmethod
    def _is_model(cls, v: Any) -> Any:
        if not (isinstance(v, type) and issubclass(v, BaseModel)):
            raise ValueError("输入、输出要是 Pydantic 模型类")
        return v

    def exit(self, key: str) -> NodeExit | None:
        return next((e for e in self.exits if e.key == key), None)


@dataclass
class NodeCall:
    """调一个节点时带的东西：库会话、运行环境（接单的 Ctx：存储、通知、设置）、谁调的、哪一单 / 哪个对象。"""

    db: Any
    ctx: Any
    by: str
    order_id: int | None = None
    subject_type: str = ""  # 流程里的对象类型（order、gather_visitor……），不是流程调的就空
    subject_id: int | None = None


class NodeResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    exit: str
    output: Any = None
    detail: str = ""


Handler = Callable[[NodeCall, Any], NodeResult]


class NodeError(RuntimeError):
    pass


_CARDS: dict[str, NodeCard] = {}
_HANDLERS: dict[str, Handler | None] = {}


def register(card: NodeCard, handler: Handler | None = None) -> NodeCard:
    """登记一个节点。同一个 id 重复登记（模块被重新导入）时以后一次为准；说明卡不全在构造 NodeCard 时就报错。"""
    if not isinstance(card, NodeCard):
        raise TypeError("register 要的是 NodeCard")
    _CARDS[card.id] = card
    _HANDLERS[card.id] = handler
    return card


def get_card(node_id: str) -> NodeCard:
    try:
        return _CARDS[node_id]
    except KeyError as e:
        raise NodeError(f"没有登记过节点 {node_id}") from e


def has_node(node_id: str) -> bool:
    return node_id in _CARDS


def has_handler(node_id: str) -> bool:
    return _HANDLERS.get(node_id) is not None


def all_cards() -> list[NodeCard]:
    return sorted(_CARDS.values(), key=lambda c: (CATEGORIES.index(c.category), c.id))


def run_node(node_id: str, call: NodeCall, data: BaseModel | dict[str, Any]) -> NodeResult:
    """按说明卡跑一个节点：校验输入 → 调 handler → 校验出口在说明卡里、输出是说明卡写的模型。"""
    card = get_card(node_id)
    handler = _HANDLERS.get(node_id)
    if handler is None:
        raise NodeError(f"节点 {node_id} 还没实现（{card.status}，归模块 {card.owner}）")
    try:
        payload = data if isinstance(data, card.input_model) else card.input_model.model_validate(
            data.model_dump() if isinstance(data, BaseModel) else data)
    except ValidationError as e:
        raise NodeError(f"节点 {node_id} 的输入不对：{e.errors()[:3]}") from e
    result = handler(call, payload)
    if not isinstance(result, NodeResult):
        raise NodeError(f"节点 {node_id} 要返回 NodeResult")
    if card.exit(result.exit) is None:
        raise NodeError(f"节点 {node_id} 返回了说明卡里没有的出口 {result.exit}")
    if result.output is not None and not isinstance(result.output, card.output_model):
        raise NodeError(f"节点 {node_id} 的输出不是 {card.output_model.__name__}")
    return result


def _fields(model: type[BaseModel]) -> list[dict[str, Any]]:
    out = []
    for name, f in model.model_fields.items():
        ann = f.annotation
        tname = getattr(ann, "__name__", None) or str(ann).replace("typing.", "")
        out.append({"name": name, "type": tname, "required": f.is_required(), "description": f.description or ""})
    return out


def card_json(card: NodeCard) -> dict[str, Any]:
    """后台「节点目录」页用：说明卡 + 输入输出的字段表。"""
    return {
        "id": card.id, "name": card.name, "description": card.description, "category": card.category,
        "tech": card.tech, "input": {"model": card.input_model.__name__, "fields": _fields(card.input_model)},
        "output": {"model": card.output_model.__name__, "fields": _fields(card.output_model)},
        "exits": [e.model_dump() for e in card.exits], "config": card.config, "emits": card.emits,
        "listens": card.listens, "replaceable": card.replaceable, "failure": card.failure,
        "owner": card.owner, "status": card.status, "runnable": has_handler(card.id),
    }
