"""交付模块自己的配置（读同一个 .env）：后台圈的开关和节奏、收成品包的检查、水印的技术参数。

业务上 Edison 会改的数不在这里，在后台「设置」页（库里的 config.delivery：水印浓淡 watermark_alpha、
提醒、改稿时限、确认来源表、发给客人的话）。测试里直接构造 `DeliverySettings(_env_file=None, ...)`，
放到 `app.state.delivery_settings`。
"""

from __future__ import annotations

from app.core.config import ModuleSettings


class DeliverySettings(ModuleSettings):
    # 后台圈：出水印图的队列、时限看门。起来后先等 DELIVERY_TICK_DELAY 秒再跑第一圈，之后每 DELIVERY_TICK_SECONDS 秒一圈
    DELIVERY_WORKER: bool = True
    DELIVERY_TICK_SECONDS: float = 15.0
    DELIVERY_TICK_DELAY: float = 20.0
    # 这么多页以内当场出图（科研绘图单张图、测试），更多进后台队列：34 页出图要十几秒到半分钟，
    # 不能占着接口请求和 SQLite 唯一的写入口（设计 4.2、第五节）
    DELIVERY_SYNC_MAX_PAGES: int = 4
    # 出图失败：隔多少秒重试、最多几次（之后通知负责人，后台点「重出图」）
    DELIVERY_RENDER_RETRY_SECONDS: float = 60.0
    DELIVERY_RENDER_MAX_ATTEMPTS: int = 3

    # 收成品包（deliver.receive）：必须交哪些最终版（按成品类型）；pptx 页数要不要和整页图张数对上
    DELIVERY_REQUIRED_FINALS: list[str] = ["PPT", "讲稿"]
    DELIVERY_CHECK_SLIDE_COUNT: bool = True

    # 提修改：整体意见（不落到某一页的）最多几条，逼客人落到页；附件单个多大
    DELIVERY_WHOLE_ITEMS_MAX: int = 3
    DELIVERY_REVISION_FILE_MAX_MB: int = 10

    # 时限看门：用掉多少还没交第一版就提醒（我的建议 0.8）
    DELIVERY_SLA_WARN_RATIO: float = 0.8
    # 不加急的单第一版压到加急承诺时长之后再发（Edison 11-19，release.py）。生产必须开；老测试在 tests/conftest.py 里关掉
    DELIVERY_HOLD_STANDARD: bool = True

    # 确认来源 free（不用确认，直接完成）只许用在这些流程里（检查 E8）
    DELIVERY_FREE_FLOWS: list[str] = ["free_gzh"]

    # 水印技术参数（设计 4.8 节）；浓淡在后台设置里（config.delivery.watermark_alpha）
    WATERMARK_LONG_SIDE: int = 1920  # 出图长边（16:9 → 1920×1080）
    WATERMARK_LONG_MIN: int = 1600  # 整页图长边下限：不收缩略图
    WATERMARK_QUALITY: int = 82
    WATERMARK_WARP: bool = True  # 每页一个轻微的随机网格扭曲（Dekel 2017）
