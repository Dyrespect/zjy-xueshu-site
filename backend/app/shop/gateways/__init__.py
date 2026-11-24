"""网关客户端：真的去调微信支付、支付宝的接口（httpx 同步客户端）；测试里换成 httpx.MockTransport，不联网。

只翻译：组请求、签名、发、验应答签名、把应答翻成字典。要不要建单、金额对不对，在 channel.web（service.py）里判断。
假网关（pay.fake）没有客户端，账本在运行时里（runtime.ShopRuntime.fake_trades）。
"""
