"""整页图收件检查（后台上传成品、制作方交件时用）：不像整页图（太小、读不出来）的当场拒。

第一期的简版水印出图已经换成模块 E 的正式实现（app/delivery/watermark.py：整页 1920、斜纹平铺、每页扭曲），
这里只留收件时的尺寸检查。出图的规格、透明度看 E 的那份。
"""

from __future__ import annotations

import io

from PIL import Image

LONG_MIN = 1600  # 整页图长边下限：不收缩略图


class WatermarkError(ValueError):
    pass


def check_page(data: bytes) -> tuple[int, int]:
    """整页图的尺寸；不像整页图（太小、读不出来）抛 WatermarkError。"""
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
    except Exception as e:  # noqa: BLE001 - 读不出来的图一律当坏图
        raise WatermarkError(f"图片读不出来：{e}") from e
    if max(w, h) < LONG_MIN:
        raise WatermarkError(f"整页图太小（长边 {max(w, h)} 像素），要 {LONG_MIN} 以上，不能给缩略图")
    return w, h
