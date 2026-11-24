"""缩略图和预览图（PRD 第五节）。原图只读，生成的图放 DATA_DIR/图库/ 下。

- 缩略图：webp，长边 480，质量 75。离线脚本 scripts/figures_build_thumbs.py 一次全部生成；
  漏了的第一次被看时补上。
- 预览图：webp，长边 1400，质量 80，下面接一条白边，白边右侧小字水印「PsyEngine 图库 · 仅供学习参考」
  （PRD 写的是右下角半透明小字、不挡主体；压在图上会盖住图右下角的字，所以挪到图下面的白边里），
  第一次被看时生成并缓存。
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

THUMB_SIDE, THUMB_QUALITY = 480, 75
PREVIEW_SIDE, PREVIEW_QUALITY = 1400, 80
WATERMARK = "PsyEngine 图库 · 仅供学习参考"
WATERMARK_ASCII = "PsyEngine · for study only"
FONT_CANDIDATES = [
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
]

_locks: dict[Path, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(p: Path) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(p, threading.Lock())


def _open_rgb(src: Path) -> Image.Image:
    im = Image.open(src)
    im = ImageOps.exif_transpose(im)
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))  # 透明底的图铺白底（网页上卡片是浅灰底）
        im = Image.alpha_composite(bg, im).convert("RGB")
    elif im.mode != "RGB":
        im = im.convert("RGB")
    return im


def _save_atomic(im: Image.Image, dest: Path, quality: int) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    im.save(tmp, "WEBP", quality=quality, method=4)
    os.replace(tmp, dest)


def make_thumb(src: Path, dest: Path) -> int:
    im = _open_rgb(src)
    im.thumbnail((THUMB_SIDE, THUMB_SIDE), Image.LANCZOS)
    _save_atomic(im, dest, THUMB_QUALITY)
    return dest.stat().st_size


def _font(size: int, font_path: Path | None) -> tuple[ImageFont.ImageFont | ImageFont.FreeTypeFont, bool]:
    for p in ([str(font_path)] if font_path else []) + FONT_CANDIDATES:
        if p and Path(p).is_file():
            try:
                return ImageFont.truetype(p, size), True
            except OSError:
                continue
    return ImageFont.load_default(size=size), False


def make_preview(src: Path, dest: Path, font_path: Path | None = None) -> int:
    """预览图：原图缩到长边 1400，下面接一条白边，水印小字写在白边右侧——不压在图上的任何东西。"""
    im = _open_rgb(src)
    im.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE), Image.LANCZOS)
    w, h = im.size
    size = max(11, min(22, round(max(w, h) * 0.014)))
    font, cjk = _font(size, font_path)
    text = WATERMARK if cjk else WATERMARK_ASCII
    probe = ImageDraw.Draw(im)
    box = probe.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    band = th + size  # 白边高度：字高再加上下各半个字
    out = Image.new("RGB", (w, h + band), (255, 255, 255))
    out.paste(im, (0, 0))
    draw = ImageDraw.Draw(out)
    margin = max(6, size // 2)
    x = max(margin, w - tw - margin) - box[0]
    y = h + (band - th) // 2 - box[1]
    draw.text((x, y), text, font=font, fill=(150, 155, 163))
    _save_atomic(out, dest, PREVIEW_QUALITY)
    return dest.stat().st_size


def ensure(kind: str, fid: int, src: Path | None, cache_dir: Path, font_path: Path | None = None) -> Path | None:
    """返回生成好的图；没有就现做一张（同一张图同时只做一次）。原图找不到返回 None。"""
    dest = cache_dir / f"{fid}.webp"
    if dest.is_file():
        return dest
    if src is None:
        return None
    with _lock_for(dest):
        if not dest.is_file():
            if kind == "thumb":
                make_thumb(src, dest)
            else:
                make_preview(src, dest, font_path)
    return dest
