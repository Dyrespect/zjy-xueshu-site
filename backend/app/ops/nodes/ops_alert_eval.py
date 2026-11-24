"""ops.alert_eval 告警检查。"""

from __future__ import annotations

from datetime import datetime

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.ops import alerts, health
from app.ops.config import kv_get, kv_set, load_config
from app.ops.models_io import AlertEvalOut, Empty


def handler(call: NodeCall, data: Empty) -> NodeResult:
    db, ctx = call.db, call.ctx
    cfg = load_config(db)
    now = data.now or ctx.now()
    # 外部依赖每 every_minutes 分钟查一次（不是每 2 分钟都连外网）
    every = cfg.rule("external_down")["params"]["every_minutes"]
    last = kv_get(db, "ext_last").get("at")
    external = cfg.rule("external_down")["enabled"] and (last is None or (now - datetime.fromisoformat(last)).total_seconds() >= every * 60)
    h = health.run(db, ctx, cfg, external=external, use_cache=False)
    if external:
        kv_set(db, "ext_last", {"at": now.isoformat()})
    out = alerts.evaluate(call, cfg, now=now, health=h)
    return NodeResult(exit="ok", output=out)


CARD = NodeCard(
    id="ops.alert_eval",
    name="告警检查",
    description="每 2 分钟按告警规则（alerts.json + 设置里的阈值）算一遍：网站报错多、数据库写不进、支付回调验签失败、支付通知没回来、"
                "水印积压、磁盘快满、备份失败、证书快到期、外部服务连不上。新出的问题开一条告警并推飞书；同一个问题去重、静默一段时间不重复推；"
                "好了自动关掉，「要立刻处理」的恢复了也说一声。",
    category="运营",
    tech=["SQLAlchemy（ops_alerts、events、ops_samples）", "run_node(\"ops.send\")（推送节点，可换）", "深健康检查 health.run"],
    input_model=Empty,
    output_model=AlertEvalOut,
    exits=[NodeExit(key="ok", label="算完了", kind="ok"), NodeExit(key="fail", label="出错（下一轮再来）", kind="fail")],
    config=["rules.<规则>.enabled / push / level / params（阈值）", "push.enabled、push.levels、push.silence_minutes、push.max_per_hour、"
            "push.notify_resolved（后台「运维 → 设置」「飞书汇报」）"],
    emits=["ops.alert_opened", "ops.alert_resolved", "ops.sent / ops.send_failed（推送节点记）"],
    listens=["无（定时算；业务数从 events 表和接口位读）"],
    replaceable=["Prometheus Alertmanager（装了 Prometheus 以后：分组、去重、静默、路由都现成）", "Uptime Kuma（网站整个挂了的外部告警）"],
    failure="每条规则单独 try，坏一条不影响别的；同一个 key 只有一条开着的告警（去重）；推送失败只记 ops.send_failed，下一轮按静默时间再推。",
    owner="运维",
    status="要新做",
)
register(CARD, handler)
