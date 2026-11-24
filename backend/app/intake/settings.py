"""接单模块自己的配置（读同一个 .env）。

业务上会经常改的数（名额、各场合必需材料和标准用时、价格表、自动发哪几类）不在这里，
在库里（`config_store.py`，后台「设置」页能改）。这里只放部署相关的：路径、开关。
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import SecretStr

from app.core.config import ModuleSettings


class IntakeSettings(ModuleSettings):
    # 开工时把材料交到哪。测试和联调一律设成临时目录，不许写真的 inbox
    FACTORY_INBOX: Path = Path("/Users/edison/Desktop/学术汇报/PPT工厂/inbox")
    # 工厂的 jobs 目录（只读：后台「从工厂选成品」列 jobs/<单>/成品/ 里的文件）
    FACTORY_JOBS: Path = Path("/Users/edison/Desktop/学术汇报/PPT工厂/jobs")
    # 交接方式：direct = 直接写 FACTORY_INBOX（网站和工厂在同一台机器）；
    # pull = 网站在服务器上，开工时把交接包存进平台存储、记一条「待领」，Mac 上 scripts/factory_pull.py 来领
    HANDOFF_MODE: Literal["direct", "pull"] = "direct"
    # pull 模式下 Mac 来领交接包用的令牌（请求头 Authorization: Bearer <令牌>），跟后台密码分开
    FACTORY_PULL_TOKEN: SecretStr = SecretStr("")
    # 制作方（Claude，在工厂里做 PPT）和业务员对话用的令牌（/api/intake/production，请求头 Authorization: Bearer）。
    # 跟 FACTORY_PULL_TOKEN、后台密码分开；空 = 这个口子关着（503）
    PRODUCTION_TOKEN: SecretStr = SecretStr("")
    # 负责人（Edison）的微信二维码图片：机器人解决不了的事发这张图。空 = 只发一句话
    OWNER_WECHAT_QR: Path | None = None
    # 付款二维码的兜底（设置页「付款渠道」里没填图片路径时用）；客服二维码（后台看）
    PAY_QR_IMAGE: Path | None = None
    SERVICE_QR_IMAGE: Path | None = None
    # 后台工人：收到消息后过几秒再让机器人回（客户常常连发几条、文字加文件）
    INTAKE_WORKER: bool = True
    INTAKE_DEBOUNCE_SECONDS: float = 3.0
    # 接待机器人（docs/任务单/12_接待机器人_设计.md）：
    # 像真人的回复节奏（看到、打字、分几条发的时间，参数在后台「接待机器人」里）；关了就批了马上发
    RECEPTION_RHYTHM: bool = True
    # 会话开头表明是 AI 助手（《人工智能生成合成内容标识办法》第四条）；生产必须开，只有老测试关
    RECEPTION_DISCLOSURE: bool = True
    # 用模型判断意图（一个小调用）；关了只用规则（关键词 + 例句相似度）
    RECEPTION_CLASSIFIER: bool = True
    # 业务上的「今天」按哪个时区算（客户和 Edison 都在国内）
    INTAKE_TIMEZONE: str = "Asia/Shanghai"
