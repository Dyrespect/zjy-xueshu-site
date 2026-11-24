"""水印出图和三条硬检查（设计第九节 E1、E2、E4）：

E1 水印版只能是整页图片（JPEG，只许 APP0；EXIF/XMP、ICC、IPTC、注释都不许）；
E2 不是缩略图（长边 < 1600 不收；出图长边统一 1920）；
E4 水印铺满（4×4 每格都有）、每页不同、扭曲真的生效、带完整单号。
每条失败信息都要有三件：错在哪、怎么改、看哪份说明。
"""

from __future__ import annotations

import io

import pytest
from PIL import Image, ImageStat

from app.delivery import watermark
from app.delivery.checks import CheckFailed, require_final_allowed, require_long_side, verify_proof
from app.delivery.watermark import WatermarkError, WatermarkSpec, order_label, render

FOOTER = round(1920 * 0.03)


def _white(w: int = 1920, h: int = 1080) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(buf, "PNG")
    return buf.getvalue()


def _mask(jpg: bytes) -> list[list[bool]]:
    """水印像素（亮度 < 245）的位置，只看页面部分（去掉底栏）。"""
    im = Image.open(io.BytesIO(jpg)).convert("L")
    w, h = im.size
    im = im.crop((0, 0, w, h - FOOTER))
    px = im.load()
    return [[px[x, y] < 245 for x in range(0, im.size[0], 2)] for y in range(0, im.size[1], 2)]


def _three_parts(e: CheckFailed) -> None:
    assert e.what and e.fix and e.doc
    assert "怎么改" in str(e) and "说明" in str(e)


# ---------------------------------------------------------------- E1 只能是整页图片

def test_e1_output_is_bare_jpeg_without_metadata():
    out = render(_white(), order_no="00137", round_no=1, page_no=5, pages=34)
    facts = verify_proof(out)
    assert out[:3] == b"\xff\xd8\xff"
    assert not {0xE1, 0xE2, 0xED, 0xFE} & set(facts.markers), "水印版里带了 EXIF/ICC/IPTC/注释 → 用 watermark.render() 出图 → 设计 4.8 节"
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG" and not im.info.get("exif") and not im.info.get("icc_profile") and "comment" not in im.info


def _jpeg(**save) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (1920, 1080), (250, 250, 250)).save(buf, "JPEG", **save)
    return buf.getvalue()


@pytest.mark.parametrize("data,word", [
    (_white(), "PNG"),
    (b"%PDF-1.4\n%%EOF", "PDF"),
    (_jpeg(exif=Image.Exif().tobytes() or b"Exif\x00\x00MM\x00*\x00\x00\x00\x08\x00\x00"), "APP1"),
    (_jpeg(comment=b"PsyEngine"), "COM"),
    (_jpeg(icc_profile=b"\x00" * 128), "APP2"),
])
def test_e1_verify_rejects_text_layers_and_metadata(data, word):
    with pytest.raises(CheckFailed) as ei:
        verify_proof(data)
    assert word in ei.value.what
    _three_parts(ei.value)


# ---------------------------------------------------------------- E2 不是缩略图

def test_e2_thumbnail_rejected_with_three_parts():
    with pytest.raises(WatermarkError, match="缩略图"):
        render(_white(1334, 750), order_no="00137", round_no=1, page_no=5, pages=34)
    with pytest.raises(CheckFailed) as ei:
        require_long_side(1334, 750, long_min=1600, page=5)
    assert "第 5 页长边 1334" in ei.value.what and "deliver_pages.py" in ei.value.fix
    _three_parts(ei.value)


@pytest.mark.parametrize("size,expect", [((1920, 1080), (1920, 1080 + FOOTER)), ((2400, 1350), (1920, 1080 + FOOTER)),
                                         ((1600, 900), (1920, 1080 + FOOTER)), ((1600, 1200), (1920, 1440 + FOOTER))])
def test_e2_output_long_side_is_1920(size, expect):
    out = render(_white(*size), order_no="00001", round_no=1, page_no=1, pages=1)
    assert Image.open(io.BytesIO(out)).size == expect
    with pytest.raises(CheckFailed):
        verify_proof(out, long_min=2000)  # 下限也真的在查


# ---------------------------------------------------------------- E4 铺满、每页不同、扭曲生效、带单号

def test_e4_covers_every_cell_of_a_4x4_grid():
    m = _mask(render(_white(), order_no="00137", round_no=1, page_no=5, pages=34))
    rows, cols = len(m), len(m[0])
    for gy in range(4):
        for gx in range(4):
            cell = [m[y][x] for y in range(gy * rows // 4, (gy + 1) * rows // 4) for x in range(gx * cols // 4, (gx + 1) * cols // 4)]
            share = sum(cell) / len(cell)
            assert share >= 0.02, f"第 {gy + 1} 行第 {gx + 1} 格水印只有 {share:.1%} → 平铺范围要盖住旋转后的整页 → 设计 4.8 节"


def _diff(a: list[list[bool]], b: list[list[bool]]) -> float:
    n = sum(len(r) for r in a)
    return sum(x != y for ra, rb in zip(a, b) for x, y in zip(ra, rb)) / n


def test_e4_pages_differ_and_warp_takes_effect():
    p5 = _mask(render(_white(), order_no="00137", round_no=1, page_no=5, pages=34))
    p6 = _mask(render(_white(), order_no="00137", round_no=1, page_no=6, pages=34))
    assert _diff(p5, p6) >= 0.03, "相邻两页水印位置一样 → 网格起点按（单号, 版次, 页码）取随机偏移 → 设计 4.8 节"
    flat = _mask(render(_white(), order_no="00137", round_no=1, page_no=5, pages=34, spec=WatermarkSpec(warp=False)))
    assert _diff(p5, flat) >= 0.02, "开不开扭曲出来一样 → warp() 没生效 → 设计 4.8 节（Dekel 2017）"
    again = _mask(render(_white(), order_no="00137", round_no=1, page_no=5, pages=34))
    assert _diff(p5, again) == 0  # 同一页重出一样（按版、按页幂等）


def test_e4_full_order_number_in_watermark_and_alpha_is_a_setting():
    assert order_label(137) == "00137" and order_label(123456) == "123456"
    assert "00137" in watermark.tile_text("00137")
    light = Image.open(io.BytesIO(render(_white(), order_no="00137", round_no=1, page_no=1, pages=1,
                                         spec=WatermarkSpec(alpha=0.16)))).convert("L")
    dark = Image.open(io.BytesIO(render(_white(), order_no="00137", round_no=1, page_no=1, pages=1,
                                        spec=WatermarkSpec(alpha=0.22)))).convert("L")
    mean = lambda im: ImageStat.Stat(im.crop((0, 0, 1920, 1080))).mean[0]  # noqa: E731
    assert mean(light) > mean(dark)
    assert watermark.spec_record(WatermarkSpec(alpha=0.16))["alpha"] == 0.16


# ---------------------------------------------------------------- 最终版关口（纯函数部分）

@pytest.mark.parametrize("stage,step,completed,voided,ok", [
    ("watermarked", "watermarked", None, False, False), ("revising", "revising", None, False, False),
    ("making", "publish", None, False, False), ("completed", "completed", "x", False, True),
    ("delivered", "delivered", "x", False, True), ("revising", "revising_after", "x", False, True),
    ("void", "void", None, True, False), ("completed", "completed", None, False, False),
])
def test_final_gate_pure(stage, step, completed, voided, ok):
    if ok:
        require_final_allowed(stage=stage, completed_at=completed, voided=voided, flow_step=step)
        return
    with pytest.raises(CheckFailed) as ei:
        require_final_allowed(stage=stage, completed_at=completed, voided=voided, flow_step=step)
    _three_parts(ei.value)
