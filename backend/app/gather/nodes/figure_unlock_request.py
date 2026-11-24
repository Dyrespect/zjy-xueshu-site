"""figure.unlock_request 要全部图库（发起）：给这个人一个专属分享码，之后交的截图、他的链接带来的人都挂在这上面。"""

from __future__ import annotations

from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.gather import service
from app.gather.config import load_config
from app.gather.models_io import UnlockIn, UnlockOut


def handler(call: NodeCall, data: UnlockIn) -> NodeResult:
    cfg = call.ctx.cfg or load_config(call.db)
    if not cfg.get("unlock_enabled", True):
        return NodeResult(exit="off", detail="「要全部图库」暂时关了")
    unlock, created = service.start_unlock(call.db, call.ctx, data.visitor, data.src, data.ip, cfg)
    if created:
        record_event(call.db, "figure.unlock_requested", f"figure_unlock:{unlock.id}",
                     {"src": data.src, "verifier": unlock.verifiers})
    return NodeResult(exit="created" if created else "existing",
                      output=UnlockOut(unlock_id=unlock.id, share_code=unlock.share_code, created=created))


CARD = NodeCard(
    id="figure.unlock_request",
    name="要全部图库（发起）",
    description="网页上点「要全部图库？」时，给这个人一个专属分享码和分享链接，告诉他三步（转发、截图、在弹层里交截图），"
                "也给「不想转发就在公众号回复关键词」那条路。之后他交的截图、他的链接带来的人，都挂在这个分享码上。",
    category="获客",
    tech=["FastAPI POST /api/gather/unlock", "表 figure_unlocks（gather_figures 流程的对象）", "前端区块 all-library-dialog",
          "微信客服那扇门默认不开（企业微信规范 3.5.11.1.1，罚企业微信账号，PPT 接单靠它）"],
    input_model=UnlockIn,
    output_model=UnlockOut,
    exits=[
        NodeExit(key="created", label="新建", kind="ok"),
        NodeExit(key="existing", label="这个访客已有一个，返回原来的", kind="ok"),
        NodeExit(key="off", label="没开", kind="fail"),
    ],
    config=["unlock_enabled：开不开（后台聚人设置）", "verifier：发起时记下用哪种核验", "share_text：复制链接时带的那句话"],
    emits=["figure.unlock_requested"],
    listens=["无"],
    replaceable=["门：网页上传（默认）/ 微信客服（默认关）——都只负责把截图交给 figure.unlock_verify"],
    failure="同一访客再点返回同一个分享码（幂等，一个人只领一次全量）；分享码 6 位、去掉 0 O 1 I L，撞了重抽。",
    owner="L",
    status="要新做",
)
register(CARD, handler)
