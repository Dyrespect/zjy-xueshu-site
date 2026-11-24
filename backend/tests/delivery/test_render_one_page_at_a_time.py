"""出水印图一页一页读整页图（第一阶段单容器内存上限 600 MB；一次全读进来 60 页大图要多占约 345 MB）。"""

from __future__ import annotations

import io

from PIL import Image

from app.delivery import versions, watermark


def _png() -> bytes:
    b = io.BytesIO()
    Image.new("RGB", (1920, 1080), (240, 240, 240)).save(b, "PNG")
    return b.getvalue()


def test_render_job_reads_each_page_just_before_rendering(monkeypatch):
    log: list[str] = []
    data = _png()

    def read(key: str) -> bytes:
        log.append(f"read {key}")
        return data

    real = watermark.render

    def render(d, **kw):
        log.append(f"render {kw['page_no']}")
        return real(d, **kw)

    monkeypatch.setattr(watermark, "render", render)
    job = versions.RenderJob(1, 1, "00001", 1, "t", [(1, "k1"), (2, "k2"), (3, "k3")], watermark.WatermarkSpec(), read)
    out = versions.render_job(job)
    assert [no for no, _ in out] == [1, 2, 3] and all(jpg[:2] == b"\xff\xd8" for _, jpg in out)
    assert log == ["read k1", "render 1", "read k2", "render 2", "read k3", "render 3"]  # 不是先全读再出
