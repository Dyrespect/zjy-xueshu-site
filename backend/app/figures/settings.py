"""图库模块自己的配置（读同一个 .env）。

找图引擎路径（FIGURE_ENGINE_PATH）、学术汇报根目录（ACADEMIC_ROOT）、向量小服务（EMBED_URL）
是底座 Settings 里的，这里只放图库独有的几项。测试里直接构造：
`FigureSettings(_env_file=None, FIGURE_RATE_LIMIT_PER_HOUR=3)`，放到 `app.state.figure_settings`。
"""

from __future__ import annotations

from pathlib import Path

from app.core.config import ModuleSettings


class FigureSettings(ModuleSettings):
    # 「要全部图库」弹层里的客服二维码图片（本机路径）；空 = 显示「客服二维码还没放上来」
    FIGURE_SERVICE_QR: Path | None = None
    # 页头「汇报 PPT 定制」和结果页最后一行链到的服务说明地址；空 = 两处都不显示
    SERVICE_URL: str = ""
    # 「要全部图库」弹层最后一行（关注公众号拿精选）；空 = 不显示这一行
    FIGURE_ACCOUNT_NOTE: str = "也可以先关注公众号 PsyEngine，回复「图库」看每周更新的精选。"
    # 向量小服务一次请求的超时（秒）。超时或连不上，这次搜索退回只用关键词
    FIGURE_EMBED_TIMEOUT: float = 2.0
    # 防刷：同一 IP 每小时每类（反馈 / 需求 / 投图 / 意见）最多几条
    FIGURE_RATE_LIMIT_PER_HOUR: int = 10
    # 预览图水印用的字体（要能显示中文）；空 = 按 macOS / Linux 常见中文字体依次找
    FIGURE_WATERMARK_FONT: Path | None = None
    # 缩略图、预览图放在对象存储（COS + CDN）时填它的网址前缀，如 https://<CDN 域名>/xueshu-tuku
    # 有值：接口返回 <前缀>/thumb/<号>.webp、<前缀>/preview/<号>.webp，/api/figures/<号>/thumb 等也跳过去，
    # 服务器不读原图、不在本地生成；空 = 本地接口（缩略图离线生成、预览图第一次被看时生成）
    FIGURE_ASSET_BASE: str = ""
    # 出处文件（scripts/figures_build_sources.py 合成的 出处.json）；空 = DATA_DIR/图库/出处.json。
    # 服务器上指向部署包里的那份（deploy/bundle/engine/出处.json）
    FIGURE_SOURCES: Path | None = None
    # 版权方要求删除后多少小时内下架（页脚「版权问题」承诺的时限；07 设计第六节第 7 条）
    FIGURE_TAKEDOWN_HOURS: int = 48
