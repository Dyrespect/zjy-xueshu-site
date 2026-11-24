"""假网关（pay.fake）的通知签名：HMAC-SHA256。钥匙是启动时随机的（或测试里给的），只在测试和本机用。"""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps({k: v for k, v in payload.items() if k != "sign"}, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def sign(secret: str, payload: dict[str, Any]) -> str:
    return hmac.new(secret.encode("utf-8"), canonical(payload), hashlib.sha256).hexdigest()


def verify(secret: str, payload: dict[str, Any]) -> bool:
    given = str(payload.get("sign", ""))
    return bool(given) and hmac.compare_digest(given, sign(secret, payload))
