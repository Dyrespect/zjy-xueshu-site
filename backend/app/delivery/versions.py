"""交付这一块的实现（节点背后的函数）：收成品包的检查、版本表、出水印图（当场或排队）、发布后记账、给交付页的页列表。

依赖：core、intake（订单、成品文件只经 service.add_deliverable / round_files 和 orders.deliverables_for_customer）。
不写订单状态（只发事件给流程引擎），不直接查成品表（scripts/check.py 第 12 条）。
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events import record_event
from app.delivery import runtime, watermark
from app.delivery.checks import DOC, CheckFailed, require_long_side
from app.delivery.models import DeliveryVersion
from app.delivery.settings import DeliverySettings
from app.intake import clock, flow, orders, service
from app.intake.config_store import load_config
from app.intake.models import PAGE_KIND, PREVIEW_KIND, FileRecord, Order
from app.intake.service import Ctx

log = logging.getLogger("app.delivery")

DEFAULT_ALPHA = 0.20
AFTER_STAGES = ("completed", "delivered")


def is_after(o: Order) -> bool:
    """已完成之后交的（已完成、已交付、已交付后再改）：直接放最终版，不出水印图。"""
    return o.stage in AFTER_STAGES or o.flow_step == "revising_after"


def watermark_alpha(db: Session) -> float:
    """水印浓淡：后台设置 config.delivery.watermark_alpha（Edison 看样张定，先用 0.20）。"""
    try:
        return float(getattr(load_config(db).delivery, "watermark_alpha", DEFAULT_ALPHA) or DEFAULT_ALPHA)
    except (TypeError, ValueError):
        return DEFAULT_ALPHA


def spec_for(db: Session, s: DeliverySettings) -> watermark.WatermarkSpec:
    return watermark.WatermarkSpec(alpha=watermark_alpha(db), long_side=s.WATERMARK_LONG_SIDE, long_min=s.WATERMARK_LONG_MIN,
                                   warp=s.WATERMARK_WARP, quality=s.WATERMARK_QUALITY)


# ---------------------------------------------------------------- 版本表

def version_of(db: Session, order_id: int, round_no: int) -> DeliveryVersion | None:
    return db.scalar(select(DeliveryVersion).where(DeliveryVersion.order_id == order_id, DeliveryVersion.round == round_no))


def versions_of(db: Session, order_id: int) -> list[DeliveryVersion]:
    return list(db.scalars(select(DeliveryVersion).where(DeliveryVersion.order_id == order_id).order_by(DeliveryVersion.round)))


def _touch(v: DeliveryVersion) -> None:
    v.updated_at = utcnow()


# ---------------------------------------------------------------- 收成品包（deliver.receive）

_SLIDE = re.compile(r"^ppt/slides/slide(\d+)\.xml$")
_HIDDEN = re.compile(rb"<p:sld\b[^>]*\bshow=\"(?:0|false)\"")


def count_slides(data: bytes, name: str = "deck.pptx") -> int:
    """pptx 里有几页（不含隐藏页：PowerPoint 导出 PDF 默认不导隐藏页）。打不开抛 CheckFailed。"""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            slides = [n for n in z.namelist() if _SLIDE.match(n)]
            hidden = sum(1 for n in slides if _HIDDEN.search(z.read(n)[:4000]))
    except (zipfile.BadZipFile, KeyError, OSError) as e:
        raise CheckFailed(f"{name} 打不开（不是完整的 pptx：{e}）", "重新导出 pptx 再交；上传断了就重传",
                          f"{DOC} 第 4.1 节") from e
    if not slides:
        raise CheckFailed(f"{name} 里一页幻灯片都没有", "交 PowerPoint 存的 .pptx（不是模板、不是 .ppt）", f"{DOC} 第 4.1 节")
    return len(slides) - hidden


def _latest_by(rows: list[FileRecord], key) -> list[FileRecord]:
    """同一个键（页码、文件名）传了几次，只认最后一次。"""
    best: dict = {}
    for f in rows:
        k = key(f)
        if k not in best or f.id > best[k].id:
            best[k] = f
    return list(best.values())


@dataclass
class PackageFacts:
    round: int
    after: bool
    finals: list[FileRecord]
    pages: list[FileRecord] = field(default_factory=list)
    slide_count: int = 0
    page_sha256: list[str] = field(default_factory=list)


def check_package(db: Session, ctx: Ctx, o: Order, s: DeliverySettings) -> PackageFacts:
    """这一版齐不齐、对不对（设计 4.1 节、第九节 E2 E3）。没过抛 CheckFailed（三件）。"""
    nxt = o.delivery_round + 1
    after = is_after(o)
    if o.stage == "void":
        raise CheckFailed("这单已经作废了", "停工，不用再交", f"{DOC} 第五节")
    if not flow.accepts(o, "package_received"):
        raise CheckFailed(f"这单现在是「{flow.stage_label(o)}」，不收成品",
                          "等开工（制作中）或客人提了修改（修改中）再交；已完成、已交付后也能交新的最终版",
                          f"{DOC} 第五节；docs/任务单/06_订单中枢契约.md 第五节第 2 条")
    finals = _latest_by([f for f in service.round_files(db, o, nxt) if f.purpose != PREVIEW_KIND], key=lambda f: f.filename)
    kinds = {f.purpose for f in finals}
    missing = [k for k in s.DELIVERY_REQUIRED_FINALS if k not in kinds]
    if missing:
        raise CheckFailed(f"这一版缺{'、'.join(missing)}", "把可编辑的 pptx 和讲稿（讲稿.docx）一起交上来："
                          "production_cli.py deliver <单> deck.pptx 讲稿.docx --pages <整页图文件夹>",
                          f"{DOC} 第 4.1 节；Edison：「等确认收货了，我们才给他们发最终ppt」（最终版要先锁在库里）")
    slides = 0
    ppts = [f for f in finals if f.purpose == "PPT"]
    if ppts:
        newest = max(ppts, key=lambda f: f.id)
        slides = count_slides(ctx.storage.read_bytes(newest.storage_key), newest.filename)
    if after:
        return PackageFacts(round=nxt, after=True, finals=finals, slide_count=slides)

    pages = sorted(_latest_by(service.round_files(db, o, nxt, role="page"), key=lambda f: f.page_no or 0),
                   key=lambda f: f.page_no or 0)
    if not pages:
        raise CheckFailed("这一版没有整页图", "用 scripts/deliver_pages.py 把 deck.pdf 按长边 1920 渲染成整页图，"
                          "deliver 时加 --pages <整页图文件夹>（出水印版要用，不能只交 pptx）", f"{DOC} 第 4.1、4.8 节")
    nos = [f.page_no for f in pages]
    want = list(range(1, len(pages) + 1))
    if None in nos or nos != want:
        have = {n for n in nos if n}
        gaps = [n for n in range(1, max(have or {0}) + 1) if n not in have]
        raise CheckFailed(f"整页图页码不连续（缺第 {'、'.join(map(str, gaps)) or '?'} 页）",
                          "文件名带页码（page-01.png、page-02.png……），从 1 连着排，整份 PDF 一起渲染",
                          f"{DOC} 第 4.1 节、第九节 E3")
    if s.DELIVERY_CHECK_SLIDE_COUNT and slides and slides != len(pages):
        lack = list(range(len(pages) + 1, slides + 1))
        more = (f"缺第 {lack[0]} 页" if len(lack) == 1 else f"缺第 {lack[0]}–{lack[-1]} 页") if lack else f"多了 {len(pages) - slides} 张"
        raise CheckFailed(f"pptx {slides} 页，整页图只有 {len(pages)} 张（{more}）" if slides > len(pages)
                          else f"pptx {slides} 页，整页图却有 {len(pages)} 张（{more}）",
                          "用这一版 pptx 导出的 deck.pdf 重新渲染整份整页图（scripts/deliver_pages.py），别混用上一版的图",
                          f"{DOC} 第 4.1 节、第九节 E3")
    shas = []
    for f in pages:
        data = ctx.storage.read_bytes(f.storage_key)
        try:
            w, h = watermark.page_size(data)
        except watermark.WatermarkError as e:
            raise CheckFailed(f"第 {f.page_no} 页（{f.filename}）读不出来", "重新渲染这一页再交", f"{DOC} 第 4.1 节") from e
        require_long_side(w, h, long_min=s.WATERMARK_LONG_MIN, page=f.page_no)
        shas.append(hashlib.sha256(data).hexdigest())
    return PackageFacts(round=nxt, after=False, finals=finals, pages=pages, slide_count=slides, page_sha256=shas)


def record_version(db: Session, o: Order, facts: PackageFacts, *, source: str, note: str, revision_id: int | None) -> DeliveryVersion:
    """收下这一版：版本表写一行（同一版重传就覆盖：断点续传、传错了重来）。"""
    v = version_of(db, o.id, facts.round)
    if v is None:
        v = DeliveryVersion(order_id=o.id, round=facts.round, created_at=utcnow())
        db.add(v)
    v.status = "final" if facts.after else "received"
    v.source, v.note, v.revision_id = source[:16], note[:2000], revision_id
    v.slide_count, v.page_count = facts.slide_count, len(facts.pages)
    v.page_file_ids = [f.id for f in facts.pages]
    v.final_file_ids = [f.id for f in facts.finals]
    v.page_sha256 = facts.page_sha256
    v.proof_file_ids, v.error, v.attempts, v.next_try_at, v.rendered_at, v.published_at = [], "", 0, None, None, None
    v.watermark_spec = {}
    _touch(v)
    db.flush()
    return v


def ensure_version(db: Session, o: Order) -> DeliveryVersion:
    """出图要的版本行；没走 deliver.receive（老接口、测试直接 submit_package）时按这一版的页图补一行。"""
    nxt = o.delivery_round + 1
    v = version_of(db, o.id, nxt)
    if v is not None and v.page_file_ids:
        return v
    pages = sorted(_latest_by(service.round_files(db, o, nxt, role="page"), key=lambda f: f.page_no or 0), key=lambda f: f.page_no or 0)
    finals = _latest_by([f for f in service.round_files(db, o, nxt) if f.purpose != PREVIEW_KIND], key=lambda f: f.filename)
    if v is None:
        v = DeliveryVersion(order_id=o.id, round=nxt, created_at=utcnow(), source="api")
        db.add(v)
    v.status = "received"
    v.page_file_ids, v.page_count = [f.id for f in pages], len(pages)
    v.final_file_ids = [f.id for f in finals]
    _touch(v)
    db.flush()
    return v


# ---------------------------------------------------------------- 出水印图

@dataclass
class RenderJob:
    version_id: int
    order_id: int
    order_no: str
    round: int
    token: str  # 版本行的 updated_at：出图期间这一版被重传了，出好的图就不要了
    pages: list[tuple[int, str]]  # （页码，整页图在存储里的 key）：出图时一页一页读，不一次全读进内存
    spec: watermark.WatermarkSpec
    read: Callable[[str], bytes]  # 按 key 读整页图（ctx.storage.read_bytes）


def load_job(db: Session, ctx: Ctx, v: DeliveryVersion, s: DeliverySettings) -> RenderJob:
    rows = {f.id: f for f in db.scalars(select(FileRecord).where(FileRecord.id.in_(v.page_file_ids or [0])))}
    pages = []
    for i, fid in enumerate(v.page_file_ids, start=1):
        f = rows.get(fid)
        if f is None or f.purpose != PAGE_KIND:
            raise watermark.WatermarkError(f"第 {i} 页的整页图找不到了")
        pages.append((f.page_no or i, f.storage_key))
    if not pages:
        raise watermark.WatermarkError("这一版没有整页图")
    return RenderJob(v.id, v.order_id, watermark.order_label(v.order_id), v.round, v.updated_at.isoformat(), pages,
                     spec_for(db, s), ctx.storage.read_bytes)


def render_job(job: RenderJob) -> list[tuple[int, bytes]]:
    """只算图，不碰库（后台圈里放到线程里跑）。整页图读一页出一页：第一阶段网站和后台任务合在一个 600 MB 的容器里，
    11-19 实测一次全读进内存时 60 页大图峰值比基线多约 345 MB，一页一页读只多一页的量（约 130 MB）。"""
    n = len(job.pages)
    out: list[tuple[int, bytes]] = []
    for no, key in job.pages:
        data = job.read(key)
        out.append((no, watermark.render(data, order_no=job.order_no, round_no=job.round, page_no=no, pages=n, spec=job.spec)))
        del data
    return out


def save_proofs(db: Session, ctx: Ctx, job: RenderJob, results: list[tuple[int, bytes]], *, by: str) -> DeliveryVersion | None:
    """出好的图存成水印版（purpose=水印版，同一版、同一页码），版本行记 ready。这一版被重传过、订单不在出图这一步了就丢掉。"""
    v = db.get(DeliveryVersion, job.version_id)
    o = db.get(Order, job.order_id)
    if v is None or o is None or v.updated_at.isoformat() != job.token:
        return None
    if o.flow_step != "proofing" or o.delivery_round + 1 != v.round:
        v.status, v.error = "failed", f"出好了，但订单已经是「{flow.stage_label(o)}」，没发布"
        _touch(v)
        return None
    ids = []
    for no, jpg in results:
        rec = service.add_deliverable(db, ctx, o, filename=f"第{v.round}版_第{no:02d}页_预览.jpg", data=jpg, kind=PREVIEW_KIND,
                                      content_type="image/jpeg", page_no=no, round_no=v.round)
        ids.append(rec.id)
    v.proof_file_ids = ids
    v.status, v.error, v.rendered_at = "ready", "", utcnow()
    v.watermark_spec = watermark.spec_record(job.spec)
    _touch(v)
    record_event(db, "delivery.watermarked", f"order:{o.id}", {
        "round": v.round, "pages": len(ids), "impl": "tile_image", "alpha": job.spec.alpha, "version": v.id, "by": by})
    return v


def mark_render_failed(db: Session, ctx: Ctx, version_id: int, error: str, s: DeliverySettings) -> DeliveryVersion | None:
    """出图出错：隔一会儿再试；用完次数记 failed、通知负责人（后台能点「重出图」）。"""
    v = db.get(DeliveryVersion, version_id)
    if v is None:
        return None
    v.attempts += 1
    v.error = error[:2000]
    if v.attempts >= s.DELIVERY_RENDER_MAX_ATTEMPTS:
        v.status, v.next_try_at = "failed", None
        ctx.notifier.send(f"#{v.order_id} 第 {v.round} 版出水印图失败 {v.attempts} 次：{error[:120]}。后台交付版本里点「重出图」",
                          link="/admin/orders", level="urgent", kind="出图失败", who=f"order:{v.order_id}")
    else:
        v.status, v.next_try_at = "rendering", utcnow() + timedelta(seconds=s.DELIVERY_RENDER_RETRY_SECONDS)
    _touch(v)
    record_event(db, "node.failed", f"order:{v.order_id}", {"node": "deliver.watermark", "round": v.round, "error": error[:300],
                                                            "attempts": v.attempts})
    return v


def queue(v: DeliveryVersion) -> None:
    v.status, v.next_try_at, v.error = "rendering", utcnow(), ""
    _touch(v)


def due_versions(db: Session, now: datetime | None = None) -> list[DeliveryVersion]:
    now = now or utcnow()
    rows = db.scalars(select(DeliveryVersion).where(DeliveryVersion.status == "rendering").order_by(DeliveryVersion.id))
    return [v for v in rows if v.next_try_at is None or v.next_try_at <= now]


def render_now(db: Session, ctx: Ctx, v: DeliveryVersion, s: DeliverySettings, *, by: str) -> DeliveryVersion | None:
    """当场出图（页数少）。出错交给 mark_render_failed（后台圈接着重试）。"""
    try:
        job = load_job(db, ctx, v, s)
        return save_proofs(db, ctx, job, render_job(job), by=by)
    except (watermark.WatermarkError, CheckFailed, OSError) as e:
        mark_render_failed(db, ctx, v.id, str(e), s)
        raise


# ---------------------------------------------------------------- 发布、放出之后记账

def mark_published(db: Session, o: Order) -> DeliveryVersion | None:
    v = version_of(db, o.id, o.delivery_round)
    if v is None:
        return None
    v.status, v.published_at = "published", utcnow()
    _touch(v)
    return v


def mark_final_released(db: Session, o: Order) -> None:
    for v in versions_of(db, o.id):
        if v.status == "final" and v.published_at is None:
            v.published_at = utcnow()
            _touch(v)


# ---------------------------------------------------------------- 给交付页：每版每页的水印图

@dataclass
class ProofPage:
    page: int
    file_id: int


@dataclass
class ProofRound:
    round: int
    published_at: datetime | None
    pages: list[ProofPage]


def proof_rounds(db: Session, o: Order) -> list[ProofRound]:
    """客人能看的水印版（只从 deliverables_for_customer 里取：已完成之后一张都没有）。版本表记了这一版用哪几张就只认那几张。"""
    allowed = [f for f in orders.deliverables_for_customer(db, o) if f.purpose == PREVIEW_KIND]
    by_round: dict[int, list[FileRecord]] = {}
    for f in allowed:
        by_round.setdefault(f.round, []).append(f)
    out = []
    for r in sorted(by_round):
        v = version_of(db, o.id, r)
        files = by_round[r]
        if v is not None and v.proof_file_ids:
            keep = set(v.proof_file_ids)
            files = [f for f in files if f.id in keep]
        files = _latest_by(files, key=lambda f: f.page_no or 0)
        pages = [ProofPage(page=f.page_no or i, file_id=f.id) for i, f in enumerate(sorted(files, key=lambda f: (f.page_no or 0, f.id)), start=1)]
        out.append(ProofRound(round=r, published_at=v.published_at if v else None, pages=pages))
    return out


def page_count_of(db: Session, o: Order) -> int:
    """最新一版有几页（提修改时页码的上限）。"""
    v = version_of(db, o.id, o.delivery_round)
    if v is not None and (v.page_count or v.slide_count):
        return v.page_count or v.slide_count
    rounds = proof_rounds(db, o)
    return len(rounds[-1].pages) if rounds else 0


def settings() -> DeliverySettings:
    return runtime.get_settings()


def fmt_when(dt: datetime | None) -> str:
    """给客人看的时间：11月21日（周六）14:30（北京时间）。"""
    if dt is None:
        return ""
    t = clock.local_now(dt)
    return f"{clock.fmt_date(t.date())}{t.hour:02d}:{t.minute:02d}"


def auto_confirm_at(db: Session, o: Order) -> datetime | None:
    """自有渠道这一版几点自动确认：最近一版交出 + auto_confirm_days（计时器归模块 B，这里只算给页面看）。"""
    if o.flow_step != "watermarked" or o.delivered_at is None:
        return None
    return o.delivered_at + timedelta(hours=load_config(db).auto_confirm_hours)
