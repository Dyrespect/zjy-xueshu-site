"""闲鱼的适配器（模块 C）。P0 走人工：Edison 在闲鱼 App 看到订单 → 后台录单出文案 → 复制进闲鱼聊天、点发货 →
交易成功或退款时在后台点一下（设计第五节第 5 条）。

闲管家「虚拟货源接口」（xgj_supply，付款当场来调我们出码）要 Edison 点头（闲鱼 10-07 的法律声明禁止没书面许可的
第三方自动化程序），签名方式、哪个字段是闲鱼订单号都没查实，没写。码池（pool）是备选，也没写。
"""

from __future__ import annotations

from app.platforms.manual import ManualAdapter


class XianyuManual(ManualAdapter):
    platform = "xy"
    name = "manual"
