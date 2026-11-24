"""全部配置项。读仓库根的 `.env`（不进 git），没有就用默认值。

- 底座的配置项在 `Settings`；业务模块自己的配置项（FACTORY_INBOX、FIGURE_SERVICE_QR……）
  放 `app/<模块>/settings.py`，继承 `ModuleSettings`（读同一个 .env），不用改这个文件。
- 新增配置项时：字段 + `.env.example` 对应分节加一行说明，两处一起改。
- 相对路径（DATA_DIR、FRONTEND_DIST）一律相对仓库根解析，跟从哪个目录启动无关。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[3] = 仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]


_ENV_CONFIG = SettingsConfigDict(
    env_file=REPO_ROOT / ".env",
    env_file_encoding="utf-8",
    env_ignore_empty=True,  # .env 里写了 `KEY=` 但没填值，按默认值处理
    extra="ignore",
)


class ModuleSettings(BaseSettings):
    """业务模块自己的配置基类。例：

        # app/intake/settings.py
        class IntakeSettings(ModuleSettings):
            FACTORY_INBOX: Path = Path("/Users/edison/Desktop/学术汇报/PPT工厂/inbox")

    测试里直接构造 `IntakeSettings(_env_file=None, FACTORY_INBOX=tmp_path)`。
    """

    model_config = _ENV_CONFIG


class Settings(BaseSettings):
    model_config = _ENV_CONFIG

    # ---- 运行 ----
    APP_ENV: Literal["dev", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: Literal["json", "text"] = "json"  # json：每行一条 JSON（带请求号、已脱敏）；text：给人看的老格式
    LOG_FILE: Path | None = None  # 有值时另外写一份 JSON 日志到这个文件（相对路径按仓库根算；轮转交给 logrotate）
    PUBLIC_BASE_URL: str = "http://127.0.0.1:8710"
    # 部署在 Cloudflare / 反向代理后面时设 true：客户端 IP 取 CF-Connecting-IP / X-Forwarded-For
    TRUST_PROXY_HEADERS: bool = False

    # ---- 数据 ----
    DATA_DIR: Path = Path("data")
    DATABASE_URL: str = ""  # 空 = sqlite:///<DATA_DIR>/app.db；PG：postgresql+psycopg://用户:密码@主机:5432/库名
    FRONTEND_DIST: Path = Path("frontend/dist")

    # ---- 数据库连接池（三档推荐值见 .env.example；设计 docs/任务单/07_底座可扩展_设计.md 第八节）----
    DB_POOL_SIZE: int = Field(default=20, ge=1, le=200)
    DB_MAX_OVERFLOW: int = Field(default=20, ge=0, le=200)
    DB_POOL_TIMEOUT: float = Field(default=30.0, gt=0)  # 拿不到连接等几秒报错
    DB_POOL_RECYCLE: int = -1  # 连接用多久换新的（秒）；托管 PG 会断空闲连接，设 1800
    DB_BUSY_TIMEOUT_MS: int = Field(default=15000, ge=100)  # 只 SQLite：等写锁最多几毫秒
    DB_LOCK_WAIT_LOG_MS: int = -1  # ≥0：等锁超过这么多毫秒记一行日志 app.db.lockwait（压测用，平时 -1 不记）

    # ---- 进程和后台任务 ----
    WEB_CONCURRENCY: int = Field(default=1, ge=1, le=64)  # 网站进程数（scripts/serve.sh 用）
    # 网站进程跑不跑后台任务。默认 false：网站只接请求，后台任务交给 python -m app.worker（设计第二节「现在」这档就分开）。
    # 11-18 压测：合在一个进程里 50 个并发 p99 到 16 秒、100 个并发卡死（后台任务等 SQLite 写锁时卡住整个事件循环）；
    # 分开后 100 个并发 p95 几十毫秒。本机开发 scripts/dev.sh 设成 true 合在一起跑。
    BACKGROUND_IN_WEB: bool = False
    WORKER_PROCESSES: int = Field(default=0, ge=0, le=32)  # scripts/serve.sh 顺带起几个 worker（0 = 不起；容器部署由编排起）
    WORKER_POLL_SEC: float = Field(default=1.0, gt=0)  # worker 多久看一次队列
    WORKER_GRACE_SEC: float = Field(default=60.0, ge=0)  # 收到退出信号后最多等手上的任务几秒
    TASK_LEASE_SEC: float = Field(default=300.0, ge=10)  # 一个任务 / 定时任务的租约多长；做得久会自动续

    # ---- 文件存储 ----
    STORAGE_BACKEND: Literal["local", "cos"] = "local"
    COS_BUCKET: str = ""  # 例 xueshu-files-1250000000（带 APPID）
    COS_REGION: str = ""  # 例 ap-shanghai
    COS_PREFIX: str = "psyppt/"  # 桶里的前缀（不碰别的项目）
    COS_SECRET_ID: SecretStr = SecretStr("")
    COS_SECRET_KEY: SecretStr = SecretStr("")
    COS_ENDPOINT: str = ""  # 空 = https://<桶>.cos.<地域>.myqcloud.com；测试指向假服务

    # ---- 限流 ----
    RATE_LIMIT_BACKEND: Literal["db", "redis"] = "db"  # 万人档换 redis（要先加 redis 包）
    REDIS_URL: str = ""

    # ---- 后台登录 ----
    ADMIN_PASSWORD: SecretStr = SecretStr("")
    SESSION_SECRET: SecretStr = SecretStr("")
    SESSION_MAX_AGE_DAYS: int = 7

    # ---- 模型（兼容 OpenAI 的接口）----
    LLM_BASE_URL: str = ""
    LLM_MODEL: str = ""
    LLM_API_KEY: SecretStr = SecretStr("")
    LLM_EXTRA_HEADERS: dict[str, str] = Field(default_factory=dict)  # JSON，如 {"x-opencode-session": "..."}
    LLM_EXTRA_BODY: dict[str, Any] = Field(default_factory=dict)  # JSON，请求体里额外带的字段

    # ---- 找图 ----
    EMBED_URL: str = ""  # 查询向量小服务；空 = 只用关键词
    FIGURE_ENGINE_PATH: Path = Path(
        "/Users/edison/Desktop/学术汇报/PPT工厂/skills/科研绘图/脚本"
    )
    ACADEMIC_ROOT: Path = Path("/Users/edison/Desktop/学术汇报")

    # ---- 通知 ----
    # 发到哪：auto = 配了 FEISHU_APP_FILE（飞书应用机器人，私聊）用它，否则配了 FEISHU_WEBHOOK（群自定义机器人）用它，都没配只写日志
    FEISHU_SENDER: Literal["auto", "app", "webhook", "log"] = "auto"
    FEISHU_WEBHOOK: SecretStr = SecretStr("")
    FEISHU_SECRET: SecretStr = SecretStr("")  # 飞书机器人开了「签名校验」才填
    # 飞书应用机器人（自建应用，如 Ruler）的凭证文件，JSON：app_id、app_secret、receive_id、receive_id_type（权限 600，不进仓库）
    FEISHU_APP_FILE: Path | None = None
    # 通知策略（app/core/notify_policy.py）：只有 urgent 立刻推；同类同一客人几分钟内合并成一条；urgent 每小时最多推几条（多的进日报）
    NOTIFY_MERGE_MINUTES: int = Field(default=10, ge=0, le=1440)
    NOTIFY_URGENT_PER_HOUR: int = Field(default=10, ge=1, le=1000)

    # ---- 企业微信「微信客服」----
    WECOM_CORPID: str = ""
    WECOM_KF_SECRET: SecretStr = SecretStr("")
    WECOM_TOKEN: SecretStr = SecretStr("")
    WECOM_AES_KEY: SecretStr = SecretStr("")
    WECOM_OPEN_KFID: str = ""

    @model_validator(mode="after")
    def _resolve_paths(self) -> "Settings":
        if not self.DATA_DIR.is_absolute():
            self.DATA_DIR = REPO_ROOT / self.DATA_DIR
        if not self.FRONTEND_DIST.is_absolute():
            self.FRONTEND_DIST = REPO_ROOT / self.FRONTEND_DIST
        if self.LOG_FILE is not None and not self.LOG_FILE.is_absolute():
            self.LOG_FILE = REPO_ROOT / self.LOG_FILE
        if self.FEISHU_APP_FILE is not None and not self.FEISHU_APP_FILE.is_absolute():
            self.FEISHU_APP_FILE = REPO_ROOT / self.FEISHU_APP_FILE
        if not self.DATABASE_URL:
            self.DATABASE_URL = f"sqlite:///{self.DATA_DIR / 'app.db'}"
        if self.APP_ENV == "prod":
            missing = [
                name
                for name in ("ADMIN_PASSWORD", "SESSION_SECRET")
                if not getattr(self, name).get_secret_value()
            ]
            if missing:
                raise ValueError(f"APP_ENV=prod 时必须配置：{', '.join(missing)}")
        if self.STORAGE_BACKEND == "cos":
            missing = [n for n in ("COS_BUCKET", "COS_REGION") if not getattr(self, n)]
            missing += [n for n in ("COS_SECRET_ID", "COS_SECRET_KEY") if not getattr(self, n).get_secret_value()]
            if missing:
                raise ValueError(f"STORAGE_BACKEND=cos 时必须配置：{', '.join(missing)}（见 .env.example 文件存储一节）")
        if self.RATE_LIMIT_BACKEND == "redis" and not self.REDIS_URL:
            raise ValueError("RATE_LIMIT_BACKEND=redis 时必须配置 REDIS_URL")
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    """进程内默认配置。测试里不要用它，直接构造 Settings(...) 传给 create_app。"""
    return Settings()
