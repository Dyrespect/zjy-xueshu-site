"""运维模块的技术开关（读同一个 .env；测试里放 app.state.ops_settings = OpsSettings(_env_file=None, ...)）。

阈值、静默、保留期、日报时间、哪些告警推送这些 Edison 会改的，不在这里，在后台「运维 → 设置」（config.py，存库里）。
这里只放：开不开、密钥文件在哪、备份放哪这类部署时定一次的。

**密钥规矩**（scripts/check.py 规矩 19）：
- 飞书 webhook 地址是密钥：只从 OPS_FEISHU_WEBHOOK_FILE 指的文件读（第一行地址，第二行签名密钥，可省），或 OPS_FEISHU_WEBHOOK；
  不进库、不进事件、不进日志，后台只显示「已配置」。
- 备份推对象存储默认关（OPS_BACKUP_COS_ENABLED=false）；关着时不读密钥文件。密钥只从 OPS_BACKUP_COS_CREDENTIALS_FILE 指的文件读，
  不从环境变量读。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr

from app.core.config import ModuleSettings


class OpsSettings(ModuleSettings):
    # ---- 定时（计数落库、聚合、清理、告警、日报、备份都由一个调度圈按 ops/jobs.json 跑）----
    OPS_TIMER_ENABLED: bool = True
    OPS_TICK_SECONDS: int = 30  # 调度圈多久看一次有没有到点的任务
    OPS_TIMEZONE: str = "Asia/Shanghai"  # 日报几点、「昨天」按哪个时区算

    # ---- 计数 ----
    OPS_METRICS_ENABLED: bool = True  # 关了：中间件照样写日志，但不计数

    # ---- 外部依赖检查（深健康检查）----
    OPS_EXTERNAL_CHECKS: bool = True  # 关了：支付网关、DeepSeek、飞书、微信客服都显示「已关」
    OPS_EXTERNAL_TIMEOUT: float = 3.0  # 秒；短，连不上就算这次失败
    OPS_HEALTH_CACHE_SECONDS: int = 60  # 深检查结果缓存多久（后台反复刷新不连外网）
    OPS_CERT_HOSTS: str = ""  # 查证书剩余天数的域名（逗号分隔）；空 = PUBLIC_BASE_URL 是 https 时取它的域名

    # ---- 推送（飞书机器人）----
    # auto：配了 OPS_FEISHU_WEBHOOK(_FILE)（运维单独一个群）用它；没配但底座配了飞书应用机器人（FEISHU_APP_FILE，Ruler 私聊）用它；
    # 再没有但底座 FEISHU_WEBHOOK 配了，走现有通知接口；都没配 = 关（只写日志，不报错）
    OPS_SENDER: Literal["auto", "feishu_webhook", "feishu_app", "core_notifier", "log"] = "auto"
    OPS_FEISHU_WEBHOOK_FILE: Path | None = None
    OPS_FEISHU_WEBHOOK: SecretStr = SecretStr("")
    OPS_FEISHU_SECRET: SecretStr = SecretStr("")

    # ---- 备份（引擎用现成的 restic；没装 restic 时用内置兜底：只拷数据库、只在本机）----
    # auto：restic 装了、OPS_RESTIC_PASSWORD_FILE 有了就用 restic，否则内置兜底；restic / builtin：点名用哪个
    OPS_BACKUP_ENGINE: Literal["auto", "restic", "builtin"] = "auto"
    OPS_BACKUP_DIR: Path | None = None  # 空 = DATA_DIR/backups（内置兜底的备份、restic 前的数据库快照、本机 restic 仓库都放这里）
    OPS_BACKUP_INCLUDE: str = "files"  # DATA_DIR 下要一起备份的目录（逗号分隔；files = 客户材料、成品、发票文件）。只有 restic 备份文件
    OPS_RESTIC_BIN: str = "restic"
    OPS_RESTIC_REPOSITORY: str = ""  # 空 = OPS_BACKUP_DIR/restic（本机仓库）；推对象存储时由下面的密钥文件拼出 s3: 地址
    OPS_RESTIC_PASSWORD_FILE: Path | None = None  # restic 仓库密码文件（Edison 生成、另存一份在别处；丢了备份就打不开）
    OPS_BACKUP_COS_ENABLED: bool = False  # 推腾讯云对象存储（restic 的 s3 仓库）：默认关，Edison 点头、密钥存进文件后才开
    OPS_BACKUP_COS_CREDENTIALS_FILE: Path | None = None  # JSON：secret_id、secret_key、bucket、region、prefix；开关关着时不读
    OPS_LITESTREAM_METRICS_URL: str = ""  # 装了 Litestream（数据库连续备份）后填它的指标地址，如 http://127.0.0.1:9090/metrics

    # ---- /api/ops/metrics（给 Prometheus 拉）----
    OPS_METRICS_TOKEN: SecretStr = SecretStr("")  # 空 = 这个地址关着（404）；拉的时候带 Authorization: Bearer <令牌>
