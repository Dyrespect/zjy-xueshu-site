"""水印出图（deliver.watermark 的实现，纯函数，只用 Pillow）：一页整页图 → 铺满斜纹水印 + 底栏的 JPEG。

规格出处：docs/任务单/07_制作与交付_设计.md 第 4.8 节（原型拿凡凡那单 34 页实测过）。
- 整页长边统一成 1920（16:9 → 1920×1080）：「不能给缩略图」，也不给能打印的高清图。
- 水印字「PsyEngine 预览稿  单号 00137」写完整单号（订单号补到 5 位），斜 30°（每页随机 ±3°）平铺、隔行错开、
  每块字随机抖动，网格起点按（单号, 版次, 页码）取随机偏移：整页都盖到、压在字上，裁不掉、抹不干净。
- 每页再做一次轻微的随机网格扭曲（8×5 格，网格点各挪 ±0.5% 图宽）：同一水印用在很多图上能被算出来去掉，
  每张随机挪位置挡不住，轻微扭曲就挡得住（Dekel 2017，Google Research）。
- 深灰字 + 白描边，浓淡（不透明度）是设置（Edison 看样张定，先用 0.20）。
- 底栏（能裁掉，只管说明不管防）：「预览稿 · 第 R 版 · 第 P / N 页」「单号 · 确认收货后发可编辑 PPT 和讲稿」。
- 新建画布再贴图、JPEG 保存不传 exif / icc_profile / comment：输出里没有任何文字层、元数据（checks.verify_proof 验）。
"""

from __future__ import annotations

import hashlib
import io
import math
import random
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from app.delivery.checks import CheckFailed, require_long_side, verify_proof

FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",  # 服务器镜像装的（deploy/Dockerfile）
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",  # 本机 Mac
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
)


class WatermarkError(ValueError):
    """出图出错（图读不出来、太小）。"""


@dataclass(frozen=True)
class WatermarkSpec:
    """一版水印用的参数（存进版本表，申诉时说得清这一版怎么出的）。"""

    alpha: float = 0.20  # 水印字不透明度（设置 config.delivery.watermark_alpha）
    long_side: int = 1920
    long_min: int = 1600
    angle: float = 30.0
    angle_jitter: float = 3.0
    font_ratio: float = 0.019  # 字高 = 图宽 1.9%（1920 宽 36 像素）
    gap_x_ratio: float = 0.55  # 横向间隔 = 0.55 个字串宽
    gap_y_ratio: float = 4.2  # 行距 = 4.2 个字高
    jitter_x: int = 6
    jitter_y: int = 4
    warp: bool = True
    warp_cols: int = 8
    warp_rows: int = 5
    warp_amp_ratio: float = 0.005  # 网格点挪 ±0.5% 图宽（1920 宽约 ±10 像素）
    stroke_ratio: float = 0.9  # 白描边不透明度 = 字的 0.9 倍
    footer_ratio: float = 0.03  # 底栏高 = 图宽 3%（1920 → 58 像素）
    quality: int = 82

    def as_dict(self) -> dict:
        return asdict(self)

    def with_alpha(self, alpha: float) -> WatermarkSpec:
        return replace(self, alpha=alpha)


def order_label(order_id: int) -> str:
    """完整单号：订单号补到 5 位（00137）。"""
    return f"{int(order_id):05d}"


@lru_cache(maxsize=16)
def _font(size: int) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    """(字体, 能不能写中文)。找不到中文字体就退回英文（单号照样在），并在出图参数里记 font=fallback。"""
    for p in FONT_CANDIDATES:
        if Path(p).is_file():
            try:
                return ImageFont.truetype(p, size), True
            except OSError:
                continue
    return ImageFont.load_default(size), False


def has_cjk_font() -> bool:
    return _font(20)[1]


def page_size(data: bytes) -> tuple[int, int]:
    """整页图的尺寸（只读头，不解码整张）。读不出来抛 WatermarkError。"""
    try:
        with Image.open(io.BytesIO(data)) as im:
            return im.size
    except Exception as e:  # noqa: BLE001 - 读不出来的图一律当坏图
        raise WatermarkError(f"图片读不出来：{e}") from e


def _rng(order_no: str, round_no: int, page_no: int, salt: str = "") -> random.Random:
    seed = hashlib.sha256(f"{order_no}|{round_no}|{page_no}|{salt}".encode()).hexdigest()
    return random.Random(seed)


def tile_layer(w: int, h: int, text: str, *, rng: random.Random, spec: WatermarkSpec) -> Image.Image:
    """整页斜纹平铺水印层（RGBA，w×h）。在比原图大的画布上铺满，旋转后裁回原图大小，再扭一下。"""
    size = max(14, round(w * spec.font_ratio))
    font, _ = _font(size)
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    box = probe.textbbox((0, 0), text, font=font, stroke_width=2)
    tw = box[2] - box[0]
    step_x = tw + round(tw * spec.gap_x_ratio)
    step_y = max(size, round(size * spec.gap_y_ratio))
    diag = int(math.hypot(w, h)) + step_x + step_y
    layer = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    fill = (40, 40, 40, round(255 * spec.alpha))
    stroke = (255, 255, 255, round(255 * spec.alpha * spec.stroke_ratio))
    ox, oy = rng.randrange(step_x), rng.randrange(step_y)
    for row, y in enumerate(range(-step_y + oy, diag, step_y)):
        shift = step_x // 2 if row % 2 else 0  # 隔行错开半格，不竖直对齐成条
        for x in range(-step_x + ox - shift, diag, step_x):
            d.text((x + rng.randint(-spec.jitter_x, spec.jitter_x), y + rng.randint(-spec.jitter_y, spec.jitter_y)),
                   text, font=font, fill=fill, stroke_width=2, stroke_fill=stroke)
    layer = layer.rotate(spec.angle + rng.uniform(-spec.angle_jitter, spec.angle_jitter), resample=Image.BICUBIC)
    left, top = (diag - w) // 2, (diag - h) // 2
    layer = layer.crop((left, top, left + w, top + h))
    return warp(layer, rng, spec) if spec.warp else layer


def warp(layer: Image.Image, rng: random.Random, spec: WatermarkSpec) -> Image.Image:
    """轻微的随机网格扭曲：网格点各自随机挪 ±amp，相邻格共用网格点，不会撕裂。"""
    w, h = layer.size
    amp = w * spec.warp_amp_ratio
    cols, rows = spec.warp_cols, spec.warp_rows
    xs = [round(w * i / cols) for i in range(cols + 1)]
    ys = [round(h * j / rows) for j in range(rows + 1)]
    # 边上的点只沿边挪，整张图的四周不会露出空白
    pts = [[(x + (rng.uniform(-amp, amp) if 0 < i < cols else 0), y + (rng.uniform(-amp, amp) if 0 < j < rows else 0))
            for i, x in enumerate(xs)] for j, y in enumerate(ys)]
    mesh = []
    for j in range(rows):
        for i in range(cols):
            ul, ur, ll, lr = pts[j][i], pts[j][i + 1], pts[j + 1][i], pts[j + 1][i + 1]
            mesh.append(((xs[i], ys[j], xs[i + 1], ys[j + 1]), (*ul, *ll, *lr, *ur)))
    return layer.transform((w, h), Image.MESH, mesh, resample=Image.BICUBIC)


def footer(w: int, left: str, right: str, spec: WatermarkSpec) -> Image.Image:
    bh = max(40, round(w * spec.footer_ratio))
    band = Image.new("RGB", (w, bh), (246, 246, 247))
    d = ImageDraw.Draw(band)
    font, _ = _font(round(bh * 0.42))
    d.line([(0, 0), (w, 0)], fill=(225, 226, 229), width=1)
    m = round(bh * 0.5)
    lb = d.textbbox((0, 0), left, font=font)
    d.text((m, (bh - (lb[3] - lb[1])) // 2 - lb[1]), left, font=font, fill=(60, 62, 66))
    rb = d.textbbox((0, 0), right, font=font)
    d.text((w - m - (rb[2] - rb[0]), (bh - (rb[3] - rb[1])) // 2 - rb[1]), right, font=font, fill=(110, 114, 120))
    return band


def tile_text(order_no: str) -> str:
    return f"PsyEngine 预览稿  单号 {order_no}" if has_cjk_font() else f"PsyEngine PREVIEW  No.{order_no}"


def render(data: bytes, *, order_no: str, round_no: int, page_no: int, pages: int, spec: WatermarkSpec | None = None) -> bytes:
    """一页整页图 → 水印 JPEG（长边 spec.long_side + 底栏）。输出过 verify_proof 才返回。"""
    spec = spec or WatermarkSpec()
    w0, h0 = page_size(data)
    try:
        require_long_side(w0, h0, long_min=spec.long_min, page=page_no)
    except CheckFailed as e:
        raise WatermarkError(str(e)) from e
    with Image.open(io.BytesIO(data)) as src:
        src.load()
        rgb = src.convert("RGBA").convert("RGB") if src.mode in ("P", "LA", "PA") else src.convert("RGB")
    scale = spec.long_side / max(w0, h0)
    w, h = round(w0 * scale), round(h0 * scale)
    if (w, h) != (w0, h0):
        rgb = rgb.resize((w, h), Image.LANCZOS)
    rng = _rng(order_no, round_no, page_no)
    layer = tile_layer(w, h, tile_text(order_no), rng=rng, spec=spec)
    marked = Image.alpha_composite(rgb.convert("RGBA"), layer).convert("RGB")

    cjk = has_cjk_font()
    left = f"预览稿 · 第 {round_no} 版 · 第 {page_no} / {pages} 页" if cjk else f"PREVIEW  v{round_no}  {page_no}/{pages}"
    right = f"单号 {order_no} · 确认收货后发可编辑 PPT 和讲稿" if cjk else f"No.{order_no}"
    band = footer(w, left, right, spec)
    canvas = Image.new("RGB", (w, h + band.height), (255, 255, 255))  # 新画布：不带原图的任何 info
    canvas.paste(marked, (0, 0))
    canvas.paste(band, (0, h))
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=spec.quality, progressive=True, optimize=True)
    out = buf.getvalue()
    verify_proof(out, long_min=spec.long_min)
    return out


def render_sample(data: bytes, *, page_no: int, pages: int, title: str, spec: WatermarkSpec | None = None) -> bytes:
    """样张（接待机器人发给客人看的示范稿，讲公开论文）：和预览稿一样铺斜纹水印，字写「样张」不写单号；底栏写第几页、讲的哪篇。
    scripts/make_samples.py 用它把公众号免费 PPT 做成带水印的 PDF。"""
    spec = spec or WatermarkSpec()
    w0, h0 = page_size(data)
    try:
        require_long_side(w0, h0, long_min=spec.long_min, page=page_no)
    except CheckFailed as e:
        raise WatermarkError(str(e)) from e
    with Image.open(io.BytesIO(data)) as src:
        src.load()
        rgb = src.convert("RGB")
    scale = spec.long_side / max(w0, h0)
    w, h = round(w0 * scale), round(h0 * scale)
    if (w, h) != (w0, h0):
        rgb = rgb.resize((w, h), Image.LANCZOS)
    rng = _rng("sample", 0, page_no, salt=title)
    text = "PsyEngine 样张  仅供参考" if has_cjk_font() else "PsyEngine SAMPLE"
    layer = tile_layer(w, h, text, rng=rng, spec=spec)
    marked = Image.alpha_composite(rgb.convert("RGBA"), layer).convert("RGB")
    left = f"样张 · 第 {page_no} / {pages} 页" if has_cjk_font() else f"SAMPLE  {page_no}/{pages}"
    right = f"PsyEngine 讲公开论文的示范稿 · {title}" if has_cjk_font() else "PsyEngine sample"
    band = footer(w, left, right[:60], spec)
    canvas = Image.new("RGB", (w, h + band.height), (255, 255, 255))
    canvas.paste(marked, (0, 0))
    canvas.paste(band, (0, h))
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=spec.quality, progressive=True, optimize=True)
    return buf.getvalue()


def spec_record(spec: WatermarkSpec, *, impl: str = "tile_image") -> dict:
    """存进版本表的出图参数（含用了什么字体）。"""
    return {**spec.as_dict(), "impl": impl, "font": "cjk" if has_cjk_font() else "fallback"}
