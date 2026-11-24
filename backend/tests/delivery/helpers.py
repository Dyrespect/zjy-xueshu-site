"""交付这几块测试共用：建 app（交付后台圈关掉，按需改当场出图的页数上限）、造一单到制作中、交一版成品。"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from pydantic import SecretStr

from app.delivery import runtime
from app.delivery.settings import DeliverySettings
from app.delivery.tick import render_due
from tests.intake.helpers import make_app, pptx_bytes

TOKEN = "maker-token-for-tests"
H = {"Authorization": f"Bearer {TOKEN}"}


def dsettings(**over: Any) -> DeliverySettings:
    values: dict[str, Any] = dict(DELIVERY_WORKER=False, DELIVERY_RENDER_RETRY_SECONDS=0)
    values.update(over)
    return DeliverySettings(_env_file=None, **values)


def delivery_app(settings, notifier, tmp_path: Path, *, model: Any = None, **ds: Any):
    app = make_app(settings, notifier, tmp_path, model=model, PRODUCTION_TOKEN=SecretStr(TOKEN))
    app.state.delivery_settings = dsettings(**ds)
    return app


def slide_png(n: int, w: int = 1920, h: int = 1080) -> bytes:
    """一页像样的整页图：白底、标题条、几行字（第 n 页）。"""
    im = Image.new("RGB", (w, h), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, round(h * 0.09)], fill=(31, 78, 156))
    for i in range(6):
        d.rectangle([120, 220 + i * 110, 120 + 900 + (i * 97 + n * 31) % 600, 250 + i * 110], fill=(60, 64, 72))
    d.text((140, 30), f"Slide {n}", fill=(255, 255, 255))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def add_package(db, ctx, o, *, pages: int = 2, slides: int | None = None, script: bool = True, page_size=(1920, 1080),
                skip: tuple[int, ...] = ()) -> None:
    """把一版成品存进库（还没交：交用 run_node("deliver.receive") 或 submit_package）。"""
    from app.intake import service
    from app.intake.models import PAGE_KIND

    service.add_deliverable(db, ctx, o, filename="deck.pptx", data=pptx_bytes(slides if slides is not None else pages), kind="PPT")
    if script:
        service.add_deliverable(db, ctx, o, filename="讲稿.docx", data=b"docx-script", kind="讲稿")
    for i in range(1, pages + 1):
        if i in skip:
            continue
        service.add_deliverable(db, ctx, o, filename=f"page-{i:02d}.png", data=slide_png(i, *page_size), kind=PAGE_KIND, page_no=i)


def maker_files(pages: int, *, slides: int | None = None, script: bool = True) -> list[tuple[str, tuple[str, bytes, str]]]:
    files = [("files", ("deck.pptx", pptx_bytes(slides if slides is not None else pages), "application/octet-stream"))]
    if script:
        files.append(("files", ("讲稿.docx", b"docx-script", "application/octet-stream")))
    files += [("pages", (f"page-{i:02d}.png", slide_png(i), "image/png")) for i in range(1, pages + 1)]
    return files


def run_queue(app) -> int:
    """跑一圈出图队列（测试里代替后台圈）。"""
    from app.intake.runtime import get_runtime

    return asyncio.run(render_due(get_runtime(app), runtime.get_settings()))
