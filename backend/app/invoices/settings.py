"""开票模块的技术配置（读同一个 .env；测试里放 app.state.invoice_settings = InvoiceSettings(_env_file=None, ...)）。

业务上要财务、Edison 改的（税率、纳税人类型、开票项目、专票开关、必填字段……）不在这里，在后台「发票 → 设置」（config.py）。
"""

from __future__ import annotations

from app.core.config import ModuleSettings


class InvoiceSettings(ModuleSettings):
    # 定时看一眼（invoice.sweep：草稿的订单完成了就推进、开票后退款提醒、过期预填清掉）：开不开、几秒一次
    INVOICE_TIMER_ENABLED: bool = True
    INVOICE_TIMER_INTERVAL_SEC: int = 600
    # 下单页预填（付款前，还没挂上订单）留几天：过了还没付款、没挂上的删掉
    INVOICE_PREFILL_TTL_DAYS: int = 7
    # 客人接口每个 IP 每小时最多几次（防撞令牌）
    INVOICE_PUBLIC_HOURLY_LIMIT: int = 120
