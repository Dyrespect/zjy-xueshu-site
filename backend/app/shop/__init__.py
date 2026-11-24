"""自有渠道和支付（模块 B）：客人在我们自己的网页上下单付款，付完马上拿到激活码。

- 节点（nodes/）：channel.web 下单、pay.wechat / pay.alipay / pay.fake 三个支付节点、trigger.confirm_timeout 超时自动确认。
- 待付款单、退款、支付通知原文放本模块自己的表（models.py）；付款成功走订单中枢的 order.create，不碰订单中枢的表。
- 签名、验签、解密、二维码是纯函数（paycore/），节点文件 import 它们，它们不 import 节点。
- 依赖只许 core 和 intake（intake 里只许 adapters、platform_texts、pricing、runtime），订单的事一律 run_node。
设计：docs/任务单/07_渠道与支付_设计.md；契约：docs/任务单/06_订单中枢契约.md。
"""
