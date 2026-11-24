"""脱敏：日志、错误摘要、运维消息里不许出现的东西，统一在这里打码（docs/任务单/07_运维与数据_设计.md 第七节第 2、5 条）。

两层：
- 按字段名：键名里带 phone / mobile / tax_id / password / secret / token / webhook / code / contact / content / text 这类的，值整个换成「***」。
- 按样子：自由文本里的手机号、18 位税号、激活码全文、Bearer 令牌、sk- 密钥、飞书 webhook、交付页 / 聊天页网址里的令牌。

只用标准库；core 里的日志格式化、请求中间件和 ops 模块都用它。宁可多打码，不要漏。
"""

from __future__ import annotations

import re
from typing import Any

MASK = "***"

# 键名（小写）里出现这些片段就整个打码。code 只按整词认（避免把 status_code 打掉）
_SENSITIVE_KEY_PARTS = (
    "phone", "mobile", "tel", "tax_id", "taxid", "password", "passwd", "secret", "token", "webhook", "authorization",
    "cookie", "apikey", "api_key", "private_key", "bank_account", "id_card", "contact", "content", "text", "body",
    "openid", "unionid", "external_userid", "payer",
)
_SENSITIVE_KEY_WORDS = {"code", "codes", "sign", "signature", "key"}

# 自由文本里的样子 → 换成什么
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # 飞书 / 企业微信群机器人 webhook（整段网址）
    (re.compile(r"https?://open\.feishu\.cn/open-apis/bot/v2/hook/[A-Za-z0-9\-]+"), "<飞书webhook>"),
    (re.compile(r"https?://open\.larksuite\.com/open-apis/bot/v2/hook/[A-Za-z0-9\-]+"), "<飞书webhook>"),
    (re.compile(r"https?://qyapi\.weixin\.qq\.com/cgi-bin/webhook/send\?key=[A-Za-z0-9\-]+"), "<企业微信webhook>"),
    # 密钥、令牌
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"), "Bearer " + MASK),
    (re.compile(r"(?<![A-Za-z0-9_])sk-[A-Za-z0-9_\-]{12,}"), "sk-" + MASK),
    (re.compile(r"oc_sk_[A-Za-z0-9_\-]{6,}"), "oc_sk_" + MASK),
    (re.compile(r"(?<![A-Za-z0-9])AKID[A-Za-z0-9]{10,}"), "AKID" + MASK),
    # 飞书 tenant_access_token：旧版 t- 开头，新版是 JWT（三段 base64url）
    (re.compile(r"(?<![A-Za-z0-9_\-])t-[A-Za-z0-9_\-]{30,}"), "t-" + MASK),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}"), "<JWT>"),
    # 带令牌的网址：交付页 /d/<令牌>、聊天 /chat/<key>、付款页 /order/pay/<令牌>、固定链接 /x/<口令>、接口里的同样几段
    (re.compile(r"(/(?:d|chat|x|order/pay|api/delivery|api/channels/web|api/invoices/order|api/invoices/checkout|api/shop/checkout"
                r"|api/shop/fake/pay)/)[A-Za-z0-9_\-]{6,}"), r"\1" + MASK),
    # 激活码：PSY- 加 9 位（只留最后 2 位方便对单）
    (re.compile(r"\bPSY-[A-Z0-9]{7}([A-Z0-9]{2})\b"), r"PSY-*******\1"),
    # 18 位统一社会信用代码 / 税号（数字和大写字母，含校验位）；15、20 位旧税号
    (re.compile(r"(?<![A-Za-z0-9])[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}(?![A-Za-z0-9])"), "<税号>"),
    (re.compile(r"(?<![A-Za-z0-9])\d{15}(?:[0-9A-Z]{5})?(?![A-Za-z0-9])"), "<长号码>"),
    # 中国大陆手机号（可带 +86 / 86 前缀、中间空格或横杠）
    (re.compile(r"(?<!\d)(?:\+?86[\s\-]?)?1[3-9]\d[\s\-]?\d{4}[\s\-]?\d{4}(?!\d)"), "<手机号>"),
    # 邮箱：留域名
    (re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})"), r"***@\1"),
]


def is_sensitive_key(key: str) -> bool:
    k = str(key).lower()
    if k in _SENSITIVE_KEY_WORDS:
        return True
    if k.endswith(("_configured", "_set", "_len", "_count", "_hint", "_ok")):
        return False  # 「有没有配」「多长」这类布尔和数字不算
    return any(p in k for p in _SENSITIVE_KEY_PARTS)


def redact_text(text: Any) -> str:
    """自由文本按样子打码。"""
    s = text if isinstance(text, str) else str(text)
    for pat, rep in _PATTERNS:
        s = pat.sub(rep, s)
    return s


def redact(obj: Any, *, depth: int = 0) -> Any:
    """字典、列表递归：敏感键名整个打码，其余字符串按样子打码。"""
    if depth > 6:
        return MASK
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if is_sensitive_key(k) and v not in (None, "", [], {}):
                out[str(k)] = MASK if not isinstance(v, bool) else v
            else:
                out[str(k)] = redact(v, depth=depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact(v, depth=depth + 1) for v in obj]
    if isinstance(obj, str):
        return redact_text(obj)
    return obj


# 日志样例检查用（scripts/check.py 规矩 19 有同样一份，只用标准库，不 import 这里）
SENSITIVE_SAMPLE_PATTERNS: dict[str, re.Pattern[str]] = {
    "手机号": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
    "激活码全文": re.compile(r"\bPSY-[A-Z0-9]{9}\b"),
    "18 位税号": re.compile(r"(?<![A-Za-z0-9])[0-9A-HJ-NPQRTUWXY]{2}\d{6}[0-9A-HJ-NPQRTUWXY]{10}(?![A-Za-z0-9])"),
    "飞书 webhook": re.compile(r"open\.feishu\.cn/open-apis/bot/v2/hook/[A-Za-z0-9\-]{8,}"),
    "Bearer 令牌": re.compile(r"(?i)bearer\s+(?!\*\*\*)[A-Za-z0-9._\-]{8,}"),
    "sk- 密钥": re.compile(r"(?<![A-Za-z0-9_])sk-(?!\*\*\*)[A-Za-z0-9_\-]{12,}"),
    "飞书令牌": re.compile(r"(?<![A-Za-z0-9_\-])t-(?!\*\*\*)[A-Za-z0-9_\-]{30,}"),
}
