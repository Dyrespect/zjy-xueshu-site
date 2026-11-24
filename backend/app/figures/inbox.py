"""收反馈、需求、投图、意见：限流、蜜罐、上传图片的检查。"""

from __future__ import annotations

import io
from datetime import timedelta

from fastapi import HTTPException, UploadFile, status
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow

ALLOWED_FORMATS = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "GIF": "gif"}
MB = 1024 * 1024

FEEDBACK_REASONS = {
    "wrong_type": "图型不对",
    "wrong_tags": "标签有错",
    "irrelevant": "和我搜的不相关",
    "unclear": "图不清楚",
    "other": "其他",
}


def check_rate(db: Session, model, ip: str, limit: int) -> None:
    """同一 IP 每小时每类最多 limit 条（按库里的记录数，不另起计数器）。"""
    since = utcnow() - timedelta(hours=1)
    n = db.scalar(select(func.count()).select_from(model).where(model.ip == ip, model.created_at >= since)) or 0
    if n >= limit:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="提交得太频繁了，过一小时再试")


def is_bot(honeypot: str | None) -> bool:
    """蜜罐字段：页面上藏起来，人不会填。填了就当机器人：照常回「收到了」，但不入库。"""
    return bool((honeypot or "").strip())


async def read_image(upload: UploadFile | None, max_mb: int, required: bool) -> tuple[bytes, str] | None:
    """读上传的图，返回 (内容, 扩展名)。不是图片、太大都给一句中文说明。"""
    if upload is None or not upload.filename:
        if required:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="请选一张图片")
        return None
    data = await upload.read(max_mb * MB + 1)
    if len(data) > max_mb * MB:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail=f"图片不能超过 {max_mb}MB")
    if not data:
        if required:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="请选一张图片")
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format or ""
            im.verify()
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="只收图片（png、jpg、webp、gif）") from None
    if fmt not in ALLOWED_FORMATS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="只收图片（png、jpg、webp、gif）")
    return data, ALLOWED_FORMATS[fmt]


def clean(s: str | None, limit: int) -> str:
    return " ".join((s or "").split())[:limit] if s else ""


def clean_text(s: str | None, limit: int) -> str:
    """保留换行的长文本。"""
    return (s or "").strip()[:limit]
