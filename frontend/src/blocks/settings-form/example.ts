import { defineBlockDemo } from "@/lib/blocks";
import type { AdminSettings } from "@/lib/admin-types";

import { SettingsForm } from "./SettingsForm";

const categories = ["一般回复", "收到文件", "问缺的材料", "进度查询", "报价", "交付和注意事项", "付款方式", "核销", "负责人微信", "转告制作方", "改稿", "排期通知", "交付"];

const settings: AdminSettings = {
  config: {
    schema_version: 3,
    occasions: {
      组会文献: {"name": "组会读文献", "must": [{"text": "要讲的论文 PDF（几篇发几篇）", "use": "PPT 的内容全从它来", "purpose": "论文", "key": ""}], "nice": [{"text": "组里或学校的 PPT 模板", "use": "有就照它做，没有就用学校配色", "purpose": "模板", "key": ""}, {"text": "老师或组里的要求（固定结构、页数）", "use": "照着排结构、定页数", "purpose": "", "key": ""}, {"text": "以前被老师问过的问题", "use": "讲稿里提前备好怎么答", "purpose": "", "key": ""}, {"text": "补充材料", "use": "正文没写透的方法和结果从这里补", "purpose": "材料", "key": ""}], "required": ["论文"], "optional_hint": "", "default_minutes": 15},
      课程文献: {"name": "课程汇报", "must": [{"text": "要讲的论文 PDF（几篇发几篇）", "use": "PPT 的内容全从它来", "purpose": "论文", "key": ""}], "nice": [{"text": "老师布置的要求", "use": "照着定结构和重点", "purpose": "", "key": ""}, {"text": "PPT 模板", "use": "有就照它做，没有就用学校配色", "purpose": "模板", "key": ""}], "required": ["论文"], "optional_hint": "", "default_minutes": 10},
      开题: {"name": "开题", "must": [{"text": "开题报告（或开题 PPT 初稿）", "use": "研究问题、方法、预期都从这里出", "purpose": "开题报告", "key": ""}], "nice": [{"text": "学校模板", "use": "有就照它做，没有就用学校配色", "purpose": "模板", "key": ""}, {"text": "老师意见", "use": "老师提过的地方在 PPT 里改到位", "purpose": "", "key": ""}, {"text": "实验材料", "use": "照着画实验流程，讲清怎么测", "purpose": "材料", "key": ""}], "required": ["开题报告"], "optional_hint": "", "default_minutes": 10},
      中期: {"name": "中期", "must": [{"text": "开题报告（或开题 PPT）", "use": "交代研究问题和当初的计划", "purpose": "开题报告", "key": ""}, {"text": "现在的进展（文稿、PPT、跑出来的结果图都行）", "use": "讲做了什么、结果怎样、接下来做什么", "purpose": "进展", "key": ""}], "nice": [{"text": "学校模板", "use": "有就照它做，没有就用学校配色", "purpose": "模板", "key": ""}, {"text": "实验材料", "use": "照着画实验流程", "purpose": "材料", "key": ""}, {"text": "分析好的结果图", "use": "结果页直接照它讲", "purpose": "数据", "key": ""}], "required": ["开题报告", "进展"], "optional_hint": "", "default_minutes": 10},
      答辩: {"name": "答辩", "must": [{"text": "毕业论文全文（Word 也行）", "use": "PPT 的内容全从它来", "purpose": "论文", "key": ""}], "nice": [{"text": "学校模板", "use": "有就照它做，没有就用学校配色", "purpose": "模板", "key": ""}, {"text": "预答辩意见", "use": "评委提过的地方重点讲清，讲稿里备好怎么答", "purpose": "", "key": ""}], "required": ["论文"], "optional_hint": "", "default_minutes": 15},
      会议: {"name": "会议报告", "must": [{"text": "论文稿或摘要", "use": "PPT 的内容全从它来", "purpose": "论文", "key": ""}], "nice": [{"text": "结果图", "use": "结果页直接照它讲", "purpose": "数据", "key": ""}, {"text": "会议对报告的要求（时长、页数、模板）", "use": "照着卡时长和版式", "purpose": "", "key": ""}], "required": ["论文"], "optional_hint": "", "default_minutes": 12},
    },
    daily_quota: 3, buffer_days: 1, queue_horizon_days: 14,
    duration_tiers: [
      { key: "light", name: "轻量", max_minutes: 15, max_pages: 20, prices: { p1: "24.9", p2_3: "34.9", p4_5: "" }, std_hours: 4, rush_hours: 2, rush: true, later_price: "19.9" },
      { key: "regular", name: "常规", max_minutes: 25, max_pages: 30, prices: { p1: "29.9", p2_3: "39.9", p4_5: "49.9" }, std_hours: 5, rush_hours: 3, rush: true, later_price: "24.9" },
      { key: "long", name: "长", max_minutes: 40, max_pages: 45, prices: { p1: "44.9", p2_3: "54.9", p4_5: "64.9" }, std_hours: 8, rush_hours: 5, rush: false, later_price: "" },
      { key: "xlong", name: "超长", max_minutes: 60, max_pages: 60, prices: { p1: "59.9", p2_3: "69.9", p4_5: "79.9" }, std_hours: 12, rush_hours: 7, rush: false, later_price: "" },
    ],
    paper_bands: [
      { key: "p1", name: "1 篇", max_papers: 1 },
      { key: "p2_3", name: "2–3 篇", max_papers: 3 },
      { key: "p4_5", name: "4–5 篇", max_papers: 5 },
    ],
    addons: [
      { key: "rush", name: "加急", price: "9.9", note: "只对轻量、常规、材料齐的单，限名额；做不到退加急费" },
      { key: "revision", name: "再改一轮", price: "9.9", note: "基础价含一轮，可以买多次" },
      { key: "find_refs", name: "帮我找文献", price: "9.9", note: "按 1 篇的价算，找到几篇都含在里面；不开放加急" },
    ],
    promise_buffer_hours: 2, find_refs_extra_hours: 2,
    page_rule_text: "页数按内容页算，不含封面、目录、过渡页、参考文献、致谢",
    rush_daily_quota: 1, work_start_hour: 9, visitor_daily_limit: 20, visitor_global_daily_limit: 500, refund_block_after: 2,
    revise_after_days: 7, auto_confirm_days: 3,
    delivery: {
      remind_before_hours: 24, revision_hours: 3, watermark_alpha: 0.2,
      confirm_sources_by_platform: {
        web: ["customer", "auto", "edison"], fk: ["customer", "auto", "edison"], manual: ["customer", "auto", "edison"],
        xhs: ["edison", "platform"], xy: ["edison"], dy: ["platform", "edison"],
      },
      texts: {},
    },
    checklists: {},
    materials: {"site_title": "下单前准备好这些", "site_lead": "按你的场合准备。必须发的齐了才开工；有的话更好的几样，能让 PPT 更贴你们组和老师的要求。", "order_head": "{name}要发这几样，直接发在这里，一次发齐最快：", "visitor_head": "{name}要准备这几样，付款认领后发我就行：", "overview_head": "资料直接发在这里，要发的主材料看场合：", "overview_tail": "告诉我是哪种场合，我把这个场合要的完整列给你。", "must_title": "必须发的：", "nice_title": "有的话更好：", "common_title": "每个场合都要说一声", "received_mark": "（收到了）", "start_rule": "资料齐了才开工，时限从开工那会儿算，不是从付款算。", "other_text": "这个场合没有固定清单：要讲的东西直接发我，我看了告诉你还缺什么。", "common": [{"text": "讲几分钟", "use": "定页数和详略", "purpose": "", "key": "duration_min"}, {"text": "哪天汇报", "use": "排期，看赶不赶得上", "purpose": "", "key": "present_date"}, {"text": "学校名", "use": "放校徽和配色", "purpose": "", "key": "school"}], "find_refs_line": {"text": "要我们找的文献方向和关键词", "use": "我们照它找文献，论文不用你发", "purpose": "", "key": "topic"}, "order": ["组会文献", "课程文献", "开题", "中期", "答辩", "会议"]},
    entry_texts: {},
    delivery_templates: { code_and_url: "激活码：{code}\n打开 {url} 查看并兑换。", code_only: "激活码：{code}" },
    deliver_text: "你会拿到：① 可编辑的 PPT，按你说的时长做；② 每页的讲稿（Word），照着能讲；③ 学校校徽和配色，或者套你发来的模板；④ 原文的图照用，原文没有、讲不清的我们按心理学好刊的画法画出来；⑤ 内容标出处，APA 格式；⑥ 含一轮修改。",
    notes_text: "1. 内容以开工时你发来的材料为准，开工后再加新的内容算新的一单；\n2. 页数按内容页算（不含封面、目录、过渡页、参考文献、致谢），上限看你买的档；\n3. 做好先给你看水印版，含一轮修改，意见请一次给齐；你确认收货后发可编辑的 PPT 和讲稿。",
    payment: { text: "在发卡站买对应货号的激活码，付完页面上就会显示激活码，复制发给我就行", link: "", qr_image: "" },
    revisions_included: 1,
    approval: Object.fromEntries(categories.map((c) => [c, false])),
    welcome_text: "你好，我是 PsyEngine 的接单助手（AI）。拿到激活码的话直接发我（PSY- 开头）；还没买的可以问我能做什么、多少钱、要多久。",
    faq: [
      { q: "能改几次", a: "含一轮修改，意见一次给齐；再改要买「再改一轮」的码" },
      { q: "退款、投诉", a: "发负责人微信" },
    ],
  },
  categories,
  purposes: ["论文", "开题报告", "进展", "材料", "数据", "模板", "其他"],
  deliverable_kinds: ["水印版", "PPT", "讲稿", "PDF", "可编辑图", "其他", "页图"],
  images: { pay_qr: false, owner_qr: false, service_qr: false },
  payment_ready: false,
  price_hash: "3f2a9c1d0e8b7a65",
  production_token: true,
  wecom: { corpid: false, secret: false, token: false, aes_key: false, open_kfid: false, callback_path: "/api/channels/wecom/callback" },
  model: { configured: true, name: "deepseek-v4.1-flash" },
  factory_inbox: "/Users/edison/Desktop/学术汇报/PPT工厂/inbox",
  handoff_mode: "direct",
  factory_pull_token: false,
};

export default defineBlockDemo({
  block: "settings-form",
  title: "后台设置",
  order: 55,
  component: SettingsForm,
  examples: [{ name: "默认（付款渠道链接还没定、企业微信还没配）", props: { settings, onSave: async () => undefined, onContactWay: async () => "" } }],
});
