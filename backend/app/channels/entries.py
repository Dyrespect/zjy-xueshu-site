"""入口登记处：每个入口节点文件末尾 `register_entry(EntrySpec(...))`。

兑换网页的按钮、出站选哪个节点（`spec_for(channel)`）都从这里来；加一个入口不改兑换页。
"""

from __future__ import annotations

from app.channels.entry_types import EntrySpec

_SPECS: dict[str, EntrySpec] = {}


def register_entry(spec: EntrySpec) -> EntrySpec:
    _SPECS[spec.node_id] = spec
    return spec


def unregister_entry(node_id: str) -> None:
    """测试里登记过假入口后收回。"""
    _SPECS.pop(node_id, None)


def all_specs() -> list[EntrySpec]:
    return sorted(_SPECS.values(), key=lambda s: (s.order, s.node_id))


def spec_for(channel: str) -> EntrySpec | None:
    return next((s for s in _SPECS.values() if s.channel == channel), None)


def spec_by_node(node_id: str) -> EntrySpec | None:
    return _SPECS.get(node_id)
