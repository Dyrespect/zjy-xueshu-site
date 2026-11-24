"""ops.health_check 深健康检查。"""

from __future__ import annotations

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.ops import health
from app.ops.config import load_config
from app.ops.models_io import HealthIn, HealthOut


def handler(call: NodeCall, data: HealthIn) -> NodeResult:
    out = health.run(call.db, call.ctx, load_config(call.db), external=data.external, use_cache=data.use_cache)
    return NodeResult(exit="ok" if out.ok else "problem", output=out)


CARD = NodeCard(
    id="ops.health_check",
    name="深健康检查",
    description="一项一行看网站现在好不好：数据库能不能写、水印出图队列、做单、磁盘、证书还有几天、备份、"
                "外部服务（支付网关、DeepSeek、飞书、微信客服）连不连得上。后台运维页打开时、告警检查时跑；结果缓存 60 秒。",
    category="运营",
    tech=["FastAPI GET /api/admin/ops/health", "SQLAlchemy（往 ops_kv 写一行心跳）", "shutil.disk_usage", "ssl（读证书到期日）",
          "httpx HEAD（只看通不通，不带密钥）", "接口位 sources.gauge / sources.external（业务读数由 app/admin/ops_sources.py 登记）"],
    input_model=HealthIn,
    output_model=HealthOut,
    exits=[NodeExit(key="ok", label="都好", kind="ok"), NodeExit(key="problem", label="有一项有问题", kind="fail")],
    config=["OPS_EXTERNAL_CHECKS、OPS_EXTERNAL_TIMEOUT、OPS_HEALTH_CACHE_SECONDS、OPS_CERT_HOSTS（.env）",
            "阈值取告警规则 disk_usage、cert_expiring、watermark_backlog、backup_failed 的设置"],
    emits=["无"],
    listens=["无"],
    replaceable=["外部拨测（Uptime Kuma）从另一台机器查 /health 和证书，跟这个互补（网站整个挂了它也能报）"],
    failure="每一项单独 try：某项出错这一项写「查不到」，别的照查；外部依赖超时算这次失败，不重试（告警要连续 3 次才报）。只读，除了一行心跳。",
    owner="运维",
    status="要新做",
)
register(CARD, handler)
