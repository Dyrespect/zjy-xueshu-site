"""下单前要客人勾的几项（下单页付款按钮上面那一组，和前端 blocks/checkout-consent 的 key 一一对上）。

- terms_privacy：已阅读并同意《用户协议》《隐私政策》。
- ai_processing：同意材料交给第三方 AI 模型处理，含境外的服务（可能出境）。个人信息保护法第三十九条要求向境外提供
  个人信息取得「单独同意」，所以单独一项、不和协议捆在一起（条文出处见 正规化缺口清单.md）。
- custom_no_refund：已了解这是按自己材料做的定制服务，开始制作后不支持仅退款（消费者权益保护法第二十五条
  「经消费者在购买时确认不宜退货的」；文案出处 文案草稿/03_下单页.md「付款前勾选」）。
"""

from __future__ import annotations

REQUIRED_CONSENTS: dict[str, str] = {
    "terms_privacy": "已阅读并同意用户协议和隐私政策",
    "ai_processing": "同意材料交给第三方 AI 模型处理（含境外，可能出境）",
    "custom_no_refund": "已了解定制服务开始制作后不支持仅退款",
}

VERSION_PATTERN = r"^\d{4}-\d{2}-\d{2}(-[a-z0-9]{1,12})?$"
