"""流程引擎（很薄）：读流程定义，按对象当前步骤和事件往前走，进到带 enter 的步骤就跑那个节点，每走一格记事件。

- 流程是数据：`app/intake/flows/<key>.json`（别的模块的流程放自己的 `flows/`，用 register_flow_dir 登记），Pydantic 校验
  （步骤、连线、条件、等待外部事件的点、循环）。换流程、加分支、换节点改文件，不改这里。
- 不只认订单：流程写明 subject（order 订单、gather_visitor 图库访客……）。对象类型用 register_subject 登记：
  表里要有 flow_key、flow_step、stage、stage_at、updated_at 这几列。订单是 subject 的一种（本文件末尾登记）。
- 这是唯一能写 `flow_step`、`stage` 的地方（scripts/check.py 拦）。
- 事件来了当前步骤没有连线接 → 不动、返回 False（幂等：重复来的事件无害）；后台手动推不是 manual 的连线 → StageError。
- 节点之间不直接调，引擎按 id 走注册表（app/core/nodes.py）；进来就跑的节点拿到触发它的事件数据（emit 的 data）。
格式和默认流程：docs/任务单/06_订单中枢契约.md 第五节。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.core.db import lock_row, utcnow
from app.core.events import record_event
from app.core.nodes import NodeCall, get_card, has_node, run_node
from app.intake.models import Order

FLOW_DIR = Path(__file__).parent / "flows"
DEFAULT_FLOW = "paid_custom"
MAX_HOPS = 20


class StageError(ValueError):
    """不合法的手动推进、或者这一步不认的动作（接口返回 409）。"""


class Cond(BaseModel):
    """条件：对象的一个字段（订单另有算出来的：addon、find_refs、platform_completed……）。不执行任意代码。"""

    field: str = Field(min_length=1, max_length=32, pattern=r"^[a-z_]+$")
    op: Literal["eq", "in", "has", "not"]
    value: Any = None


class Edge(BaseModel):
    on: str = Field(min_length=1)  # 事件名，或 exit:<进入节点的出口>
    to: str = Field(min_length=1)
    when: list[Cond] = Field(default_factory=list)
    manual: bool = False  # 后台能不能手动推这条
    loop: bool = False  # 回到前面的状态（修改后再交一版）要显式标
    label: str = ""


class Step(BaseModel):
    id: str = Field(min_length=1, max_length=32, pattern=r"^[a-z_]+$")
    stage: str = Field(max_length=16)
    node: str = Field(min_length=1)  # 这一步由哪个节点负责（节点目录里能查到说明卡）
    label: str = ""
    enter: str | None = None  # 一进来就跑的节点；它的出口用 on="exit:<出口>" 的连线接走
    terminal: bool = False
    edges: list[Edge] = Field(default_factory=list)


class StageDef(BaseModel):
    key: str = Field(min_length=1, max_length=16)
    label: str = Field(min_length=1)


class Flow(BaseModel):
    key: str = Field(min_length=1, max_length=32, pattern=r"^[a-z_]+$")
    subject: str = Field(default="order", min_length=1, max_length=32, pattern=r"^[a-z_]+$")
    name: str
    description: str
    stages: list[StageDef]  # 有顺序：除了标 loop 的连线，状态只往后走
    start: str
    steps: list[Step]

    @model_validator(mode="after")
    def _check(self) -> Flow:
        ids = [s.id for s in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("步骤 id 重复")
        if self.start not in ids:
            raise ValueError(f"起点 {self.start} 不在步骤里")
        order = [s.key for s in self.stages]
        for s in self.steps:
            if s.stage not in order:
                raise ValueError(f"步骤 {s.id} 的状态 {s.stage} 没在 stages 里声明")
            if s.terminal and s.edges:
                raise ValueError(f"终点 {s.id} 不能再有连线")
            for e in s.edges:
                if e.to not in ids:
                    raise ValueError(f"步骤 {s.id} 的连线 {e.on} 指向不存在的步骤 {e.to}")
                target = next(x for x in self.steps if x.id == e.to)
                if order.index(target.stage) < order.index(s.stage) and not e.loop:
                    raise ValueError(f"步骤 {s.id} 的连线 {e.on} 回到了前面的状态 {target.stage}，要标 loop")
                if e.on.startswith("exit:") and not s.enter:
                    raise ValueError(f"步骤 {s.id} 没有 enter 节点，不能接 {e.on}")
        return self

    def step(self, step_id: str) -> Step | None:
        return next((s for s in self.steps if s.id == step_id), None)

    def stage_label(self, key: str) -> str:
        return next((s.label for s in self.stages if s.key == key), key)

    def stage_keys(self) -> list[str]:
        return [s.key for s in self.stages]


# ---------------------------------------------------------------- 对象类型、流程文件夹

@dataclass
class SubjectSpec:
    name: str
    model: type
    facts: Callable[[Any], dict[str, Any]] | None = None  # 条件能用的字段；不给就直接读对象的同名字段
    stage_event: str = "flow.stage"  # 每走一格记的事件类型
    by_id: str = "subject_id"  # 进来就跑的节点输入里，对象 id 用哪个名字（订单是 order_id）


_SUBJECTS: dict[str, SubjectSpec] = {}
_FLOW_DIRS: list[Path] = [FLOW_DIR]
_CACHE: dict[str, Flow] = {}


def register_subject(spec: SubjectSpec) -> None:
    """登记一种能走流程的对象（表里要有 flow_key、flow_step、stage、stage_at、updated_at、id）。"""
    for col in ("flow_key", "flow_step", "stage", "stage_at", "updated_at", "id"):
        if not hasattr(spec.model, col):
            raise ValueError(f"{spec.model.__name__} 没有 {col} 列，不能走流程")
    _SUBJECTS[spec.name] = spec


def register_flow_dir(path: Path) -> None:
    """别的模块的流程文件夹（放自己的 flows/*.json）。"""
    if path not in _FLOW_DIRS:
        _FLOW_DIRS.append(path)
        _CACHE.clear()


def _subject_of(obj: Any) -> SubjectSpec:
    for spec in _SUBJECTS.values():
        if isinstance(obj, spec.model):
            return spec
    raise StageError(f"{type(obj).__name__} 没登记成能走流程的对象")


def check_nodes(flow: Flow) -> list[str]:
    """流程里用到的节点都登记了、enter 节点的出口连线都在说明卡里。返回问题列表（空 = 没问题）。"""
    problems = []
    if flow.subject not in _SUBJECTS:
        problems.append(f"流程的 subject {flow.subject} 没登记")
    for s in flow.steps:
        for nid in filter(None, (s.node, s.enter)):
            if not has_node(nid):
                problems.append(f"步骤 {s.id} 用了没登记的节点 {nid}")
        if s.enter and has_node(s.enter):
            card = get_card(s.enter)
            for e in s.edges:
                if e.on.startswith("exit:") and card.exit(e.on.removeprefix("exit:")) is None:
                    problems.append(f"步骤 {s.id} 接的出口 {e.on} 不在节点 {s.enter} 的说明卡里")
    return problems


_NODE_LOADERS: list[Callable[[], None]] = []
_nodes_loaded = False


def add_node_loader(loader: Callable[[], None]) -> None:
    """加载节点的口子：流程里用到别的模块的节点（交付的 deliver.*、以后渠道、聚人的），引擎读流程前要先把它们登记上。
    给了 loader（比如拼装层的 registry.import_all_nodes）就用它；没给就按目录自己找（_discover_node_packages）。"""
    global _nodes_loaded
    if loader not in _NODE_LOADERS:
        _NODE_LOADERS.append(loader)
        _nodes_loaded = False


def _discover_node_packages() -> None:
    """默认的加载法：app 下每个带 nodes/ 包的业务模块都导入一遍（按目录找，不点名，所以接单不依赖别的模块的代码）。
    不起 app 的脚本、单测读流程时也能把交付等模块的节点登记上。"""
    import importlib

    import app as app_pkg

    for root in app_pkg.__path__:
        for d in sorted(Path(root).iterdir()):
            if d.name.startswith(("_", ".")) or d.name == "core" or not (d / "nodes" / "__init__.py").is_file():
                continue
            importlib.import_module(f"app.{d.name}.nodes")


def ensure_nodes() -> None:
    """流程要用的节点都登记上（读流程、跑节点前调；第二次起不再加载）。"""
    global _nodes_loaded
    import app.intake.nodes  # noqa: F401 接单这一块的节点

    if _nodes_loaded:
        return
    _nodes_loaded = True  # 先置上：加载过程中有人再调不会转圈
    for loader in _NODE_LOADERS or [_discover_node_packages]:
        loader()


def _flow_path(key: str) -> Path | None:
    for d in _FLOW_DIRS:
        p = d / f"{key}.json"
        if p.is_file():
            return p
    return None


def load_flow(key: str) -> Flow:
    if key in _CACHE:
        return _CACHE[key]
    path = _flow_path(key)
    if path is None:
        raise StageError(f"没有流程 {key}")
    flow = Flow.model_validate(json.loads(path.read_text(encoding="utf-8")))
    if flow.key != key:
        raise ValueError(f"流程文件 {path.name} 里的 key 是 {flow.key}，要跟文件名一样")
    ensure_nodes()
    problems = check_nodes(flow)
    if problems:
        raise ValueError(f"流程 {key} 不对：" + "；".join(problems))
    _CACHE[key] = flow
    return flow


def all_flows() -> list[Flow]:
    keys = sorted({p.stem for d in _FLOW_DIRS for p in d.glob("*.json")})
    return [load_flow(k) for k in keys]


# ---------------------------------------------------------------- 条件

def _facts(obj: Any) -> dict[str, Any]:
    spec = _subject_of(obj)
    if spec.facts is not None:
        return spec.facts(obj)
    table = getattr(obj, "__table__", None)
    if table is not None:
        return {c.key: getattr(obj, c.key) for c in table.columns}
    return {k: v for k, v in vars(obj).items() if not k.startswith("_")}


def _ok(cond: Cond, facts: dict[str, Any]) -> bool:
    v = facts.get(cond.field)
    if cond.op == "eq":
        return v == cond.value
    if cond.op == "in":
        return v in (cond.value or [])
    if cond.op == "has":
        return cond.value in (v or set())
    if cond.op == "not":
        return v != cond.value if not isinstance(v, (set, list, tuple)) else cond.value not in v
    return False


def _pick(step: Step, on: str, obj: Any, *, manual: bool = False) -> Edge | None:
    facts = _facts(obj)
    for e in step.edges:
        if e.on == on and (e.manual or not manual) and all(_ok(c, facts) for c in e.when):
            return e
    return None


# ---------------------------------------------------------------- 走

def flow_of(obj: Any) -> Flow:
    return load_flow(obj.flow_key or DEFAULT_FLOW)


def current_step(obj: Any) -> Step | None:
    if not obj.flow_step:
        return None
    return flow_of(obj).step(obj.flow_step)


def is_closed(obj: Any) -> bool:
    """不再往下走的：终点、旧草稿（没有步骤）。"""
    step = current_step(obj)
    return step is None or step.terminal


def stage_label(obj: Any) -> str:
    if not obj.flow_step:
        return "旧草稿"
    return flow_of(obj).stage_label(obj.stage)


def accepts(obj: Any, event: str) -> bool:
    step = current_step(obj)
    return step is not None and _pick(step, event, obj) is not None


def _call(db: Session, ctx: Any, obj: Any, flow: Flow, by: str) -> tuple[NodeCall, dict[str, Any]]:
    spec = _SUBJECTS[flow.subject]
    is_order = flow.subject == "order"
    call = NodeCall(db, ctx, by, obj.id if is_order else None, subject_type=flow.subject, subject_id=obj.id)
    return call, {spec.by_id: obj.id, "subject_type": flow.subject, "subject_id": obj.id}


def _walk(db: Session, ctx: Any, obj: Any, flow: Flow, to: str, *, event: str, by: str,
          data: dict[str, Any] | None) -> list[tuple[str, str, str]]:
    """从当前步骤沿连线走到 to，进到带 enter 的步骤就跑节点、按出口接着走。返回走过的 (from_step, to_step, event)。

    每进一步就先把对象的 flow_step、stage 改成这一步（节点看到的是自己所在的步骤，比如 gate.final 要「已完成」）。
    """
    hops: list[tuple[str, str, str]] = []
    here, target, ev = obj.flow_step, to, event
    for _ in range(MAX_HOPS):
        hops.append((here, target, ev))
        step = flow.step(target)
        here = target
        obj.flow_step, obj.stage = step.id, step.stage
        if not step.enter:
            break
        call, ids = _call(db, ctx, obj, flow, by)
        # via=flow：节点知道自己是作为「进入这一步就跑」被引擎调的（同一个节点被别的模块直接调时是 via=call）；
        # data：触发这一趟的事件带的数据
        result = run_node(step.enter, call, {**(data or {}), **ids, "via": "flow", "event": ev})
        edge = _pick(step, f"exit:{result.exit}", obj)
        if edge is None:
            break  # 没接的出口：停在这一步等
        target, ev = edge.to, f"exit:{result.exit}"
    else:
        raise RuntimeError(f"流程 {flow.key} 在 {flow.subject} {obj.id} 上走了 {MAX_HOPS} 步还没停，连线可能成环了")
    return hops


def _settle(db: Session, obj: Any, flow: Flow, hops: list[tuple[str, str, str]], *, start_step: str,
            by: str, why: str) -> None:
    final = hops[-1][1] if hops else obj.flow_step
    step = flow.step(final)
    obj.flow_step, obj.stage = step.id, step.stage
    if final == start_step and len(hops) > 1:
        return  # 进了判断步骤又回到原地（比如收资料 → 开工判断 → 收资料）：不算换步骤，不记
    now = utcnow()
    spec = _SUBJECTS[flow.subject]
    for frm, to, ev in hops:
        fs, ts = flow.step(frm), flow.step(to)
        record_event(db, spec.stage_event, f"{flow.subject}:{obj.id}", {
            "flow": flow.key, "from_step": frm, "to_step": to, "from": fs.stage if fs else "",
            "to": ts.stage if ts else "", "event": ev, "by": by, "why": why[:200],
        })
    obj.stage_at = now
    obj.updated_at = now


def start(db: Session, ctx: Any, obj: Any, flow_key: str | None = None, *, by: str, why: str = "",
          data: dict[str, Any] | None = None) -> Any:
    """新对象放到流程起点（起点有 enter 节点就跑）。"""
    flow = load_flow(flow_key or obj.flow_key or DEFAULT_FLOW)
    if not isinstance(obj, _SUBJECTS[flow.subject].model):
        raise StageError(f"流程 {flow.key} 是给 {flow.subject} 的，不是 {type(obj).__name__}")
    obj.flow_key = flow.key
    obj.flow_step = ""
    hops = _walk(db, ctx, obj, flow, flow.start, event="start", by=by, data=data)
    _settle(db, obj, flow, hops, start_step="", by=by, why=why)
    return obj


def emit(db: Session, ctx: Any, obj: Any, event: str, *, by: str, why: str = "",
         data: dict[str, Any] | None = None) -> bool:
    """事件来了：当前步骤有接它的连线（条件满足）就走过去。没有 → False，不动。"""
    lock_row(db, obj)  # PG：先锁这一行再看当前步骤，两个事件同时来只有一个走得动（SQLite 写会话本来就独占）
    if not obj.flow_step:
        return False
    flow = flow_of(obj)
    step = flow.step(obj.flow_step)
    if step is None or step.terminal:
        return False
    edge = _pick(step, event, obj)
    if edge is None:
        return False
    start_step = obj.flow_step
    hops = _walk(db, ctx, obj, flow, edge.to, event=event, by=by, data=data)
    _settle(db, obj, flow, hops, start_step=start_step, by=by, why=why)
    return True


def manual_options(obj: Any) -> list[dict[str, str]]:
    """后台能手动推的连线（流程里标了 manual 的）。"""
    step = current_step(obj)
    if step is None:
        return []
    flow = flow_of(obj)
    facts = _facts(obj)
    out = []
    for e in step.edges:
        if e.manual and all(_ok(c, facts) for c in e.when):
            to = flow.step(e.to)
            out.append({"on": e.on, "to": e.to, "stage": to.stage, "stage_label": flow.stage_label(to.stage),
                        "label": e.label or f"推到「{flow.stage_label(to.stage)}」"})
    return out


def push(db: Session, ctx: Any, obj: Any, on: str, *, by: str, why: str) -> Any:
    """后台手动推一条 manual 连线；不是 manual 的、当前步骤没有的 → StageError。"""
    lock_row(db, obj)
    step = current_step(obj)
    if step is None or step.terminal:
        raise StageError(f"现在是「{stage_label(obj)}」，不能再推")
    edge = _pick(step, on, obj, manual=True)
    if edge is None:
        names = "、".join(o["label"] for o in manual_options(obj)) or "没有能手动推的"
        raise StageError(f"「{stage_label(obj)}」这一步不能手动推「{on}」（现在能推：{names}）")
    flow = flow_of(obj)
    start_step = obj.flow_step
    hops = _walk(db, ctx, obj, flow, edge.to, event=on, by=by, data=None)
    _settle(db, obj, flow, hops, start_step=start_step, by=by, why=why or "后台手动推")
    return obj


def seed_stage(obj: Any, step_id: str, flow_key: str = DEFAULT_FLOW) -> None:
    """迁移、测试用：直接把对象放到某个步骤（不跑节点、不记事件）。业务代码不许用。"""
    flow = load_flow(flow_key)
    step = flow.step(step_id)
    if step is None:
        raise StageError(f"流程 {flow_key} 没有步骤 {step_id}")
    obj.flow_key = flow.key
    obj.flow_step = step.id
    obj.stage = step.stage
    obj.stage_at = utcnow()


# ---------------------------------------------------------------- 订单这种对象

def order_facts(order: Order) -> dict[str, Any]:
    tier, _, band = (order.sku or "").partition("-")
    return {
        "platform": order.platform or "",
        "source": order.source or "",
        "sku": order.sku or "",
        "tier": order.tier_key or tier,
        "band": order.band_key or band,
        "addon": {a.get("key") for a in (order.addons or [])},
        "rush": bool(order.rush),
        "find_refs": any(a.get("key") == "find_refs" for a in (order.addons or [])),
        "platform_completed": order.platform_completed_at is not None,  # 平台的「已完成」来得早，先记下的事实
    }


register_subject(SubjectSpec("order", Order, order_facts, stage_event="intake.stage", by_id="order_id"))
