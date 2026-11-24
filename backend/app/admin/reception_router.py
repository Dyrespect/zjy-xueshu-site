"""后台：接待机器人的知识库（/api/admin/reception，整个要登录；docs/任务单/12_接待机器人_设计.md 第三节）。

- 看、改：表明身份的三种写法和用哪个、负责人微信、意图卡（怎么认、回什么、引到哪、什么时候转负责人、示范）、
  要问的几件事、禁用说法、节奏参数。保存前整份校验（表明身份那句必须同时有「AI」和「生成」）。
- 试一句：输入客人的一句话，看规则会判成哪类（不调模型），以及一条示范回复按现在的节奏几秒后发出。
"""

from __future__ import annotations

import random
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.deps import get_db
from app.intake import clock
from app.intake.reception import intent as rintent
from app.intake.reception import kb as rkb
from app.intake.reception import rhythm as rrhythm
from app.intake.reception import style as rstyle
from app.intake.runtime import get_runtime

router = APIRouter(prefix="/reception", tags=["admin"])


SAMPLE_MAX_MB = 20  # 微信客服发文件上限 20MB


def _public(kb: rkb.ReceptionKB) -> dict[str, Any]:
    """给后台页面的：样张不带存储位置。"""
    data = kb.model_dump(mode="json")
    for x in data.get("samples", []):
        x.pop("storage_key", None)
        x["ready"] = bool(x.get("filename"))
    return data


@router.get("")
def get_kb(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"kb": _public(rkb.load(db))}


class KbIn(BaseModel):
    kb: dict[str, Any]


@router.put("")
def put_kb(body: KbIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    old = rkb.load(db)
    data = dict(body.kb)
    samples = []
    for i, x in enumerate(data.get("samples") or []):  # 样张文件只能走上传接口换；这里只改标题和说明
        keep = old.samples[i] if i < len(old.samples) else None
        samples.append({**{k: v for k, v in x.items() if k != "ready"}, "filename": keep.filename if keep else "",
                        "storage_key": keep.storage_key if keep else "", "size": keep.size if keep else 0})
    data["samples"] = samples
    try:
        kb = rkb.ReceptionKB.model_validate(data)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first.get("loc", ()))
        raise HTTPException(400, detail=f"设置不对（{where}）：{first.get('msg', '')}".replace("Value error, ", "")) from e
    rkb.save(db, kb, by="edison")
    db.commit()
    return {"kb": _public(rkb.load(db))}


class TryIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)
    last_bot: str = Field(default="", max_length=300)
    reply: str = Field(default="", max_length=500, description="一条示范回复（用空行分几条），看节奏和说话检查")


@router.post("/try")
def try_one(body: TryIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    kb = rkb.load(db)
    route = rintent.classify_rules(kb, [body.text], ["text"], body.last_bot)
    ranked = sorted(route.scores.items(), key=lambda kv: -kv[1])[:4]
    out: dict[str, Any] = {
        "intents": [{"id": i, "name": kb.card(i).name if kb.card(i) else i} for i in route.intents],
        "how": route.how, "answering": route.answering,
        "scores": [{"id": i, "name": kb.card(i).name if kb.card(i) else i, "score": s} for i, s in ranked],
    }
    if body.reply.strip():
        parts = rstyle.segments(body.reply, max_segments=kb.style.segments_for("wecom"))
        now = utcnow()
        times = rrhythm.schedule(kb.rhythm, last_customer_at=now, now=now, local_now=clock.local_now(now),
                                 customer_chars=len(body.text), segments=parts, rng=random.Random(body.text))
        out["reply"] = [{"text": p, "after_s": round((t - now) / timedelta(seconds=1), 1)} for p, t in zip(parts, times, strict=True)]
        out["problems"] = [f"{p.what}：{p.why}" for p in rstyle.problems(body.reply, kb, route.intents)]
    return out


@router.post("/samples/{slot}")
async def upload_sample(slot: int, request: Request, file: UploadFile = File(...), title: str = Form(""),
                        db: Session = Depends(get_db)) -> dict[str, Any]:
    """换一份样张（带水印的 PDF，scripts/make_samples.py 做的）：第 slot 份（0–2），传了就替换。"""
    kb = rkb.load(db)
    if not 0 <= slot <= min(2, len(kb.samples)):
        raise HTTPException(400, detail="样张最多 3 份（第 1–3 份）")
    data = await file.read()
    if not data.startswith(b"%PDF"):
        raise HTTPException(400, detail="要传 PDF（scripts/make_samples.py 做出来的带水印样张）")
    if len(data) > SAMPLE_MAX_MB * 1024 * 1024:
        raise HTTPException(400, detail=f"超过 {SAMPLE_MAX_MB}MB，微信客服发不了：少放几页再传")
    name = (file.filename or f"样张{slot + 1}.pdf").replace("/", "_")[-120:]
    key = get_runtime(request.app).ctx.storage.save(data, folder="reception/samples", filename=name)
    item = {"title": title.strip() or (kb.samples[slot].title if slot < len(kb.samples) else name.rsplit(".", 1)[0]),
            "about": kb.samples[slot].about if slot < len(kb.samples) else "", "filename": name, "storage_key": key, "size": len(data)}
    samples = [x.model_dump() for x in kb.samples]
    if slot < len(samples):
        samples[slot] = item
    else:
        samples.append(item)
    kb = rkb.ReceptionKB.model_validate({**kb.model_dump(mode="json"), "samples": samples})
    rkb.save(db, kb, by="edison")
    db.commit()
    return {"kb": _public(kb)}
