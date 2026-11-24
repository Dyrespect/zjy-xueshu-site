"""交付这一块会失败的检查（顶层设计第十四节约束层第 4、5 条和「品味翻成机械规则」）。

每条失败都说三件事：错在哪、怎么改、去看哪份说明。三条硬检查：
1. 最终版（无水印 pptx、讲稿）只在订单「已完成」之后发：`require_final_allowed`。
2. 水印版只能是整页图片、不带文字层或元数据：`verify_proof`（JPEG，只许 APP0，不许 EXIF/XMP/IPTC/注释/ICC）。
3. 图片尺寸下限（不给缩略图）：`require_long_side`。
接口、节点、后台圈都调这里，测试（backend/tests/delivery/test_checks.py）盯着每一条。
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

DOC ="docs/任务单/07_制作与交付_设计.md"


class CheckFailed(ValueError):
    """一条检查没过。str() 是给人看的一整句：错在哪 → 怎么改 → 看哪。"""

    def __init__(self, what: str, fix: str, doc: str) -> None:
        self.what, self.fix, self.doc = what, fix, doc
        super().__init__(f"{what}。怎么改：{fix}。说明：{doc}")

    def as_dict(self) -> dict[str, str]:
        return {"what": self.what, "fix": self.fix, "doc": self.doc}


# ---------------------------------------------------------------- 1. 最终版只在已完成之后

FINAL_STAGES = ("completed", "delivered")


def require_final_allowed(*, stage: str, completed_at: object, voided: bool, flow_step: str = "") -> None:
    """订单不是「已完成」（或之后：已交付、已交付后再改）就不许拿最终版。作废了的一律不给。"""
    after = stage in FINAL_STAGES or (flow_step == "revising_after")
    if voided or not after or completed_at is None:
        raise CheckFailed(
            "这单还没到「已完成」，不能发可编辑的 PPT 和讲稿" if not voided else "这单作废了，不发最终版",
            "先确认收货（自有渠道客人点按钮或 3 天自动确认，平台单等平台确认后在后台点），订单到「已完成」才放；"
            "下载和发文件只走 orders.deliverables_for_customer",
            f"{DOC} 第 4.6 节；顶层设计第十四节约束层第 4 条",
        )


# ---------------------------------------------------------------- 2. 水印版只能是整页图片

# JPEG 里允许出现的段：SOI、APP0（JFIF）、DQT、SOFn、DHT、DRI、SOS、RSTn、EOI。别的 APPn（EXIF/XMP、ICC、IPTC……）和 COM 都不许
_ALLOWED_MARKERS = {0xD8, 0xE0, 0xDB, 0xC4, 0xDD, 0xDA, 0xD9} | set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC} | set(range(0xD0, 0xD8))
_MARKER_NAMES = {0xE1: "APP1（EXIF/XMP）", 0xE2: "APP2（ICC 色彩）", 0xED: "APP13（IPTC/Photoshop）", 0xFE: "COM（注释）"}


@dataclass(frozen=True)
class ProofFacts:
    width: int
    height: int
    markers: tuple[int, ...]


def _markers(data: bytes) -> list[int]:
    """走一遍 JPEG 的段头，返回段类型（扫描数据里的字节不算）。"""
    out, i, n = [], 2, len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            raise ValueError("段头不对")
        m = data[i + 1]
        if m == 0xFF:  # 填充
            i += 1
            continue
        out.append(m)
        if m == 0xD9:
            break
        if 0xD0 <= m <= 0xD7 or m == 0x01:
            i += 2
            continue
        seg = int.from_bytes(data[i + 2:i + 4], "big")
        if m == 0xDA:  # 扫描数据：跳到下一个不是 RSTn / 填充的段头
            j = i + 2 + seg
            while j + 1 < n:
                if data[j] == 0xFF and data[j + 1] not in (0x00, *range(0xD0, 0xD8)):
                    break
                j += 1
            i = j
            continue
        i += 2 + seg
    return out


def verify_proof(data: bytes, *, long_min: int = 1600) -> ProofFacts:
    """水印版必须是 JPEG 整页图：没有任何文字层、元数据段；长边不小于下限。没过抛 CheckFailed。"""
    fix = "用 app/delivery/watermark.py 的 render() 出图（新建画布、保存时不传 exif / icc_profile / comment）"
    where = f"{DOC} 第 4.8 节；顶层设计第十四节约束层第 5 条"
    if not data.startswith(b"\xff\xd8\xff"):
        head = "PDF" if data.startswith(b"%PDF") else ("PNG" if data.startswith(b"\x89PNG") else "不是 JPEG")
        raise CheckFailed(f"水印版不是 JPEG 整页图（是 {head}）", fix, where)
    try:
        markers = _markers(data)
    except (ValueError, IndexError) as e:
        raise CheckFailed(f"水印版 JPEG 读不通（{e}）", fix, where) from e
    bad = [m for m in markers if m not in _ALLOWED_MARKERS]
    if bad:
        names = "、".join(_MARKER_NAMES.get(m, f"0xFF{m:02X}") for m in dict.fromkeys(bad))
        raise CheckFailed(f"水印版里带了文字或元数据段：{names}", fix, where)
    with Image.open(io.BytesIO(data)) as im:
        w, h = im.size
    require_long_side(w, h, long_min=long_min, what="水印版")
    return ProofFacts(w, h, tuple(markers))


# ---------------------------------------------------------------- 3. 尺寸下限

def require_long_side(w: int, h: int, *, long_min: int, what: str = "整页图", page: int | None = None) -> None:
    if max(w, h) < long_min:
        who = f"第 {page} 页" if page is not None else what
        raise CheckFailed(
            f"{who}长边 {max(w, h)} 像素，是缩略图（要 {long_min} 以上）",
            "用 scripts/deliver_pages.py 把 deck.pdf 按长边 1920 渲染成整页图再交（工厂 预览/ 里的 slide-NN.png 是 100 DPI 缩略图，不能用）",
            f"{DOC} 第 4.8 节「尺寸检查」；Edison：「水印要加上去，不能给缩略图」",
        )
