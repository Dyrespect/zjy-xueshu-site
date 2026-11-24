"""接单的表。状态在库里，模型只能通过工具记事实（架构第四节）。

- 客户 Customer：一个渠道里的一个人（网页聊天一个浏览器 / 微信客服一个 external_userid）。
- 会话 Customer：一个渠道里的一个访客（咨询、问价都在会话里，还不是订单）。
- 订单 Order：付了钱的一单（平台付款、自有网页付款时建；码池的码认领时建）。可以还没有会话（customer_id 空）。
  状态 = 流程定义里的步骤（flow_step）和它标的状态（stage），只有 intake/flow.py 能写。契约：docs/任务单/06_订单中枢契约.md。
- 消息 Message：客户看得到的对话（收到的、真的发出去的）。机器人写了还没批的在 Outbox。
- 文件 FileRecord：客户发的材料、成品、修改意见附件。存储里的相对路径只给后端用，不出站。
- 待发 Outbox：所有要发给客户的话都先进这里（待批 → 已批 → 已发 / 发送失败；或不发）。
  channels 取「已批」的去发；intake 不 import channels。
- 一趟 BotRun：机器人每跑一次留一条（给模型的情况、工具调用、回复、用量），能回放。
- 任务 Job：收到消息后写一张，工人到点领（同一客户连发几条合成一趟）。
- 修改意见 Revision、设置 KV。
- 交接 Handoff：每次开工交接一条。direct 模式直接写了工厂 inbox；pull 模式交接包存在平台存储里，
  等 Mac 上的 scripts/factory_pull.py 来领（待领 → 已领），领完删掉交接包（材料原件还在存储里）。
- 激活码 ActivationCode：一笔付款的凭证（按货号）。平台付款时发（带平台单号），或后台按货号批量生成卖码池。
  认领（order.claim 节点）原子：没用 → 用了；认领记录 CodeRedemption 一枚码一行（唯一）。撤单退回「没用」，退款作废。
  核销尝试 CodeAttempt 记每一次（防撞库：同一会话 1 小时错 5 次锁 1 小时）。
- 制作方会话 ProductionMessage：业务员（机器人）和制作方（Claude，在工厂里做 PPT）之间的消息，每单一条线：
  开单说明、补充要求、问题、回答、进度、成品、改稿单。制作方凭 PRODUCTION_TOKEN 走 /api/intake/production。
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, utcnow

# 订单状态（流程里每个步骤标的状态）的中文名。流程文件里也带名字，这里是默认流程的，给不想读流程的地方用
STAGE_LABELS: dict[str, str] = {
    "paid": "已付款",
    "claimed": "已认领",
    "collecting": "收资料",
    "making": "制作中",
    "watermarked": "已交水印版",
    "revising": "修改中",
    "completed": "已完成",
    "delivered": "已交付",
    "void": "作废",
    "": "旧草稿",  # 11-18 之前「客户一开口就建一单」留下的、没付款的单
}
CLOSED_STAGES = ("delivered", "void", "")  # 不再走的（会话再说话不算这单）

OUTBOX_STATUS_LABELS: dict[str, str] = {
    "pending": "待批",
    "approved": "已批",
    "sent": "已发",
    "failed": "发送失败",
    "rejected": "不发",
}

HANDOFF_STATUS_LABELS: dict[str, str] = {
    "direct": "直接写入",
    "ready": "待领",
    "claimed": "已领",
}

MATERIAL_PURPOSES = ("论文", "开题报告", "进展", "材料", "数据", "模板", "参考", "其他")  # 参考：需求卡里传的旧 PPT、导师意见截图（只看不算必交）
DELIVERABLE_KINDS = ("水印版", "PPT", "讲稿", "PDF", "可编辑图", "其他")  # 水印版以外都是最终版（已完成才发）
PREVIEW_KIND = "水印版"
PAGE_KIND = "页图"  # 整页底图（role=page）：只在后端给出水印图用，任何接口都不返回
PLATFORMS = ("fk", "xy", "dy", "xhs", "web", "manual", "legacy")

CODE_STATUS_LABELS: dict[str, str] = {"unused": "没用", "used": "用了", "void": "作废"}

# 制作方会话里的消息类型。to_maker：业务员 → 制作方；to_sales：制作方 → 业务员
PRODUCTION_KINDS_TO_MAKER = ("开单说明", "补充要求", "问题", "回答", "改稿单")
PRODUCTION_KINDS_TO_SALES = ("进度", "问题", "回答", "成品")


class Customer(Base):
    __tablename__ = "intake_customers"
    __table_args__ = (UniqueConstraint("channel", "external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel: Mapped[str] = mapped_column(String(16))  # web | wecom
    external_id: Mapped[str] = mapped_column(String(128))  # 网页：随机长 key；微信客服：external_userid
    open_kfid: Mapped[str] = mapped_column(String(64), default="")
    nickname: Mapped[str] = mapped_column(String(64), default="")
    source: Mapped[str] = mapped_column(String(128), default="")  # 从哪来（进线 scene）
    human_takeover: Mapped[bool] = mapped_column(Boolean, default=False)  # 「我来接」：机器人停在这个客户上
    note: Mapped[str] = mapped_column(Text, default="")
    last_customer_msg_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_activity_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    bot_seen_msg_id: Mapped[int] = mapped_column(Integer, default=0)  # 机器人已经处理到哪条客户消息
    owner_qr_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 上次发负责人微信二维码（24 小时内不重复发）
    terms_sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 这个会话里发过「交付什么 + 注意事项」
    # 客户与记忆（模块 D 的 customer.memory 写，经 orders.set_customer_memory）：同一个人网页、微信两个会话同一个 person_id
    person_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    memory_brief: Mapped[str] = mapped_column(Text, default="", server_default="")  # 给助手：老客户记得的
    handoff_brief: Mapped[str] = mapped_column(Text, default="", server_default="")  # 给制作方：进开单说明
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Order(Base):
    __tablename__ = "intake_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # 流程（只有 intake/flow.py 写 flow_step、stage）
    flow_key: Mapped[str] = mapped_column(String(32), default="paid_custom", server_default="paid_custom")
    flow_step: Mapped[str] = mapped_column(String(32), default="", server_default="")
    stage: Mapped[str] = mapped_column(String(16), default="", server_default="", index=True)
    stage_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    voided_from: Mapped[str] = mapped_column(String(16), default="", server_default="")  # 作废时停在哪个状态
    hold_reason: Mapped[str] = mapped_column(String(64), default="", server_default="")  # 暂停：平台上申请了退款（不开工、不交下一版、不发最终版）
    hold_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    void_reason: Mapped[str] = mapped_column(String(16), default="", server_default="")  # return 撤单退码 | refund 退款作废码

    # 哪一笔付款（平台、单号、买家）、什么货号
    platform: Mapped[str] = mapped_column(String(16), default="", server_default="", index=True)
    source: Mapped[str] = mapped_column(String(64), default="", server_default="")  # 最早从哪来：图库、公众号、小红书……（周报算「哪来的单」）
    platform_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    buyer_id: Mapped[str] = mapped_column(String(128), default="", server_default="")
    paid_amount: Mapped[str] = mapped_column(String(16), default="", server_default="")
    sku: Mapped[str] = mapped_column(String(48), default="", server_default="")
    band_key: Mapped[str] = mapped_column(String(16), default="", server_default="")
    addons: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # 已付的加购 [{key, code, by, at}]

    # 谁认领的（会话）；客户合并归模块 D
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("intake_customers.id"), nullable=True, index=True)
    wechat_external_userid: Mapped[str] = mapped_column(String(128), default="", server_default="")
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    # 模型通过工具记的事实（Edison 在后台也能改）
    occasion: Mapped[str] = mapped_column(String(16), default="")
    title: Mapped[str] = mapped_column(String(256), default="")
    duration_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_default: Mapped[bool] = mapped_column(Boolean, default=False)  # 客户没给，按场合给的默认值
    duration_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)  # 默认值客户点头了
    present_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    present_date_text: Mapped[str] = mapped_column(String(64), default="")  # 客户原话：「下周三」
    school: Mapped[str] = mapped_column(String(64), default="")
    language: Mapped[str] = mapped_column(String(16), default="")
    structure_req: Mapped[str] = mapped_column(Text, default="")  # 页数 / 结构的硬要求
    requirement_quotes: Mapped[list[str]] = mapped_column(JSON, default=list)  # 组里 / 老师 / 自己的要求原话
    paper_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 客户说的篇数
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 客户要求的页数（内容页）

    # 货号拆出来的时长档、价、码
    tier_key: Mapped[str] = mapped_column(String(32), default="", server_default="")  # 时长档
    quoted_price: Mapped[str] = mapped_column(String(32), default="")  # 这单的价：货号价 + 同笔加购
    code_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 基础码
    redeemed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 认领时间（旧名，跟 claimed_at 一起写）
    extra_revisions: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 加购的修改轮数
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 付款时间（平台给的；码池的码是认领时间）
    rush: Mapped[bool] = mapped_column(Boolean, default=False)  # 这单按加急做（gate.ready 判断；后台也能给）
    due_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 承诺开工后几小时交第一版
    needs_edison: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # 发了负责人微信的事（后台看）

    # 排期和流转（代码写）
    queued_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    eta_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    handoff_folder: Mapped[str] = mapped_column(String(256), default="")
    maker_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 制作方说「开始做」
    maker_done_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 制作方说「做好了」
    ready_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    delivery_round: Mapped[int] = mapped_column(Integer, default=0)  # 交过几次稿
    revision_used: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 客户在交付页点「确认收货」
    feedback: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 到「已完成」
    platform_completed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 平台说已完成（来得早也先记下，发布水印版时按它直接放最终版）
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 最终版发出（到「已交付」）
    voided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 作废（旧列 cancelled_at 改名）

    delivery_token: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class FileRecord(Base):
    __tablename__ = "intake_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("intake_customers.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("intake_orders.id"), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(16), default="material")  # material | deliverable | page（整页底图，不出站）| revision | voice
    filename: Mapped[str] = mapped_column(String(256))
    size: Mapped[int] = mapped_column(Integer, default=0)
    content_type: Mapped[str] = mapped_column(String(128), default="")
    storage_key: Mapped[str] = mapped_column(String(512))  # Storage 返回的相对路径，只给后端用
    purpose: Mapped[str] = mapped_column(String(16), default="")  # 材料：论文/开题报告/…；成品：PPT/讲稿/…
    note: Mapped[str] = mapped_column(String(256), default="")
    round: Mapped[int] = mapped_column(Integer, default=0)  # 成品属于第几次交付
    page_no: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 整页图、水印图是第几页
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Message(Base):
    __tablename__ = "intake_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("intake_customers.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("intake_orders.id"), nullable=True)
    direction: Mapped[str] = mapped_column(String(8))  # in | out
    sender: Mapped[str] = mapped_column(String(16))  # customer | bot | edison | system
    kind: Mapped[str] = mapped_column(String(16), default="text")  # text | file | image | voice | event
    text: Mapped[str] = mapped_column(Text, default="")
    file_id: Mapped[int | None] = mapped_column(ForeignKey("intake_files.id"), nullable=True)
    asset: Mapped[str] = mapped_column(String(32), default="")  # 发出去的固定图片：pay_qr
    outbox_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    channel_msgid: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)  # 微信客服 msgid，去重
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class Outbox(Base):
    __tablename__ = "intake_outbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("intake_customers.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("intake_orders.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(16))
    recipient: Mapped[str] = mapped_column(String(128))
    kind: Mapped[str] = mapped_column(String(16), default="text")  # text | image | file
    text: Mapped[str] = mapped_column(Text, default="")
    file_id: Mapped[int | None] = mapped_column(ForeignKey("intake_files.id"), nullable=True)
    asset: Mapped[str] = mapped_column(String(32), default="")  # pay_qr
    category: Mapped[str] = mapped_column(String(32), default="一般回复")
    author: Mapped[str] = mapped_column(String(16), default="bot")  # bot | edison | system
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    auto: Mapped[bool] = mapped_column(Boolean, default=False)  # 按设置自动批的
    reasons: Mapped[list[str]] = mapped_column(JSON, default=list)  # 为什么这么回（工具调用摘要）
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    original_text: Mapped[str] = mapped_column(Text, default="")  # 改过再发时，机器人原来写的
    error: Mapped[str] = mapped_column(String(512), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    # 到这个时间才发（接待机器人模拟真人回复节奏；空 = 批了就发）。见 docs/任务单/12_接待机器人_设计.md 第六节
    send_after: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class BotRun(Base):
    __tablename__ = "intake_bot_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("intake_customers.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    model: Mapped[str] = mapped_column(String(64), default="")
    situation: Mapped[str] = mapped_column(Text, default="")  # 这一趟给模型的「现在的情况」+ 新消息
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    reply: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    requests: Mapped[int] = mapped_column(Integer, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Job(Base):
    __tablename__ = "intake_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("intake_customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending | running | done | failed
    run_after: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Revision(Base):
    __tablename__ = "intake_revisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("intake_orders.id"), index=True)
    text: Mapped[str] = mapped_column(Text, default="")  # 改稿单全文（由 items 拼出来）
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)  # 逐页：[{page, text}]，page 空 = 整体意见
    based_on_round: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 改的是第几版
    file_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    free: Mapped[bool] = mapped_column(Boolean, default=True)  # 含的轮数里的（用完了就是 False，只记下）
    status: Mapped[str] = mapped_column(String(16), default="open")  # open | done
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class KV(Base):
    """后台「设置」页改的业务参数（名额、场合表、价格表、自动发……），整段 JSON 存。"""

    __tablename__ = "intake_kv"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Handoff(Base):
    """一次开工交接。direct：已经写进工厂 inbox；pull：交接包（zip：材料 + 要求.md + 聊天记录.md）等 Mac 来领。"""

    __tablename__ = "intake_handoffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("intake_orders.id"), index=True)
    mode: Mapped[str] = mapped_column(String(8))  # direct | pull
    status: Mapped[str] = mapped_column(String(16), index=True)  # direct | ready | claimed
    folder: Mapped[str] = mapped_column(String(256))  # 文件夹名（客户昵称）；direct 是实际写的，pull 是建议的
    files: Mapped[list[str]] = mapped_column(JSON, default=list)  # 交接包里的文件名
    package_key: Mapped[str] = mapped_column(String(512), default="")  # 交接包在存储里的相对路径；领完清空
    package_size: Mapped[int] = mapped_column(Integer, default=0)
    package_sha256: Mapped[str] = mapped_column(String(64), default="")
    claimed_folder: Mapped[str] = mapped_column(String(256), default="")  # Mac 上实际写进的文件夹名
    claimed_by: Mapped[str] = mapped_column(String(128), default="")  # 哪台机器领的
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    claimed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ActivationCode(Base):
    """激活码 = 一笔付款的凭证。code 存规范写法 PSY-XXXXXXXXX；状态 unused → used（认领）/ void（退款、手动作废）。
    撤单退回 unused。一笔平台订单一枚码：(platform, platform_order_id) 唯一（单号空不撞）。"""

    __tablename__ = "intake_activation_codes"
    __table_args__ = (UniqueConstraint("platform", "platform_order_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    sku: Mapped[str] = mapped_column(String(48), index=True)  # 基础货号 / 加购货号 / legacy-旧档
    addons: Mapped[list[str]] = mapped_column(JSON, default=list)  # 同一笔买的加购（只有基础码会有）
    platform: Mapped[str] = mapped_column(String(16), default="fk", server_default="fk")
    platform_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    buyer_id: Mapped[str] = mapped_column(String(128), default="", server_default="")
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    paid_amount: Mapped[str] = mapped_column(String(16), default="", server_default="")
    status: Mapped[str] = mapped_column(String(8), default="unused", index=True)
    batch: Mapped[str] = mapped_column(String(32), default="", index=True)  # 一次生成一批
    note: Mapped[str] = mapped_column(String(256), default="")
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("intake_orders.id"), nullable=True, index=True)
    customer_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class CodeRedemption(Base):
    """认领记录：一枚码只能成功认领一次（code 唯一）。撤单退码时删掉这行（事件里有记录）。"""

    __tablename__ = "intake_code_redemptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(16), unique=True)
    code_id: Mapped[int] = mapped_column(Integer)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    customer_id: Mapped[int] = mapped_column(Integer, index=True)
    channel: Mapped[str] = mapped_column(String(16), default="web")  # web | wecom
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class CodeAttempt(Base):
    """每一次核销尝试（成没成都记）。防撞库按「同一客户 1 小时内失败几次」算。"""

    __tablename__ = "intake_code_attempts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("intake_customers.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    given: Mapped[str] = mapped_column(String(64), default="")  # 客户发的原样（截断）
    result: Mapped[str] = mapped_column(String(16))  # ok | not_found | used | void | expired | wrong | legacy | locked
    counts: Mapped[bool] = mapped_column(Boolean, default=False)  # 算不算一次「错」（撞库计数）
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class ProductionMessage(Base):
    """制作方会话的一条。direction：to_maker（业务员写给制作方）| to_sales（制作方写给业务员）。

    to_maker 的：制作方拉过就记 read_at。to_sales 的：机器人转告过客户就记 relayed_at
    （微信客服 48 小时窗口关着时先不转，等客户下次说话一起说）。
    """

    __tablename__ = "intake_production_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("intake_orders.id"), index=True)
    direction: Mapped[str] = mapped_column(String(8))  # to_maker | to_sales
    kind: Mapped[str] = mapped_column(String(8))  # 开单说明 补充要求 问题 回答 进度 成品 改稿单
    author: Mapped[str] = mapped_column(String(16), default="bot")  # bot | system | maker | edison
    text: Mapped[str] = mapped_column(Text, default="")
    file_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    read_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    relayed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)


class Brief(Base):
    """需求卡（一单一张，docs/任务单/09_需求引导_方案.md）：客人点选的场合、听众、时长、语言、模板、重点、不要什么、
    最像哪份样张；确认卡由代码按模板拼（app/intake/brief.py，不调模型）。

    「确认了」= confirmed_at 有值且 confirmed_version == version（确认之后谁再改一次，version + 1，就要重新确认）。
    流程里的闸口节点 gate.brief_confirmed 只看这一条；状态还是引擎写，这张表不碰 flow_step / stage。
    """

    __tablename__ = "intake_briefs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("intake_orders.id"), unique=True, index=True)
    answers: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {题目 key: {"choice": 选项 key | [..] | "__default__", "note": 一句话}}
    version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # 每改一次 + 1
    updated_by: Mapped[str] = mapped_column(String(16), default="", server_default="")  # customer | edison
    confirmed_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    confirm_method: Mapped[str] = mapped_column(String(16), default="", server_default="")  # customer 客人点「对，开工」| proxy 负责人代确认
    confirmed_by: Mapped[str] = mapped_column(String(16), default="", server_default="")
    confirm_note: Mapped[str] = mapped_column(String(256), default="", server_default="")  # 代确认时写的依据（客人在聊天里怎么说的）
    card_text: Mapped[str] = mapped_column(Text, default="", server_default="")  # 确认那一刻的确认卡全文（留痕）
    sent_back_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 负责人改了再发给客人确认
    sent_back_note: Mapped[str] = mapped_column(String(256), default="", server_default="")
    remind_from: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 从这时起算多久没确认就提醒（认领、发回、确认后又改）
    reminded_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
