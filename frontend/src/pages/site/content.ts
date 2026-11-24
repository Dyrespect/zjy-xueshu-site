/**
 * 官网各页的字。出处：psyppt静态站/build.py 第 0 节（字一个没改，只把价格、轮数、天数换成价目接口的数），
 * 再往上是 文案草稿/08_交付说明和注意事项.md、2026-11-18_定价/方案.md。
 * 价格、页数、时限、含几轮改、自动确认几天一律从 /api/shop/catalog（订单中枢 sku.catalog）填，这里不写一个数（check.py 规矩 10）。
 */
import type { ShopCatalog } from "@/lib/shop-types";

export const HERO = {
  eyebrow: "组会 · 开题 · 中期 · 答辩 · 会议报告",
  title: "让汇报不再|卡在 PPT 上", // 「|」处可以换行：手机上断成「让汇报不再 / 卡在 PPT 上」
  lead: "一顿外卖钱起，|一份专业的心理学汇报 PPT。",
  text: "面向心理学研究生和博士生。你发来论文或材料，我们按你的汇报时长做好。",
  meta: "元起，按汇报时长和材料篇数定价，下单前都写清楚。", // 前面接起价
};

/**
 * 首屏看稿器（官网v2方案.md H1）：一份英文组会文献汇报翻四页（试次 → 频率标记 → 刺激空间 → 处理流程）。
 * 11-18 夜第三轮：Edison 点名「IRIS 凡凡」，主窗口逐页选定；只写论文出处，不写客户是谁。图见 lib/site-media.ts
 */
export const VIEWER = {
  slides: [
    { key: "n16", label: "第 19 页 · Setup and Trial Procedure" },
    { key: "n17", label: "第 16 页 · Frequency Tagging (SSVEP)" },
    { key: "n18", label: "第 17 页 · Stimulus Space" },
    { key: "n19", label: "第 21 页 · EEG Processing Pipeline" },
  ] as const,
  title: "组会文献汇报 · 讲 Park (2018), Developmental Cognitive Neuroscience",
  caption: "点下面的缩略图翻页。",
};

/**
 * 首页 01：英文原图 → 我们重画的图（官网v2方案.md H2，第三轮、第四轮主窗口定：凡凡第 26 页、吴婧怡第 12 页）。原图截自各单材料里的论文 PDF（矢量，4 倍渲染）。
 * 图注是我写的草稿，等 Edison 改。表 2 算 PPV 那组挪到样张页。
 */
export const COMPARE = {
  no: "01",
  eyebrow: "原文到汇报页",
  h: "英文原图，|我们重画成这样。",
  lead: "原文的图翻译重绘，读法写在旁边；原文没画全的补上，参数照原文标齐。",
  groups: [
    {
      original: "y07",
      result: "n08",
      originalLabel: "原文 · Wei et al. (2017) 图 1",
      resultLabel: "汇报页 · 组会汇报第 26 页",
      marks: [],
      no: "图 1",
      caption: "原文图 1 是英文的三系统示意；我们翻译重绘，三个系统用颜色分开，右边一段话讲清渴求怎么放大冲动、削弱控制。",
      source: "Wei et al. (2017), Frontiers in Psychiatry，图 1。",
      layout: "side",
    },
    {
      original: "y09",
      result: "n31",
      originalLabel: "原文 · Rafiee et al. (2023) 图 1",
      resultLabel: "汇报页 · 组会文献汇报第 12 页",
      marks: [],
      no: "图 2",
      caption: "原文图 1 只画了面孔这一种刺激；我们把原图放进来、红框标出刺激帧，旁边补画面孔、声音、视听三种通道，写清每种用的什么材料、多少个试次。",
      source: "Rafiee et al. (2023), Psychoneuroendocrinology，图 1。",
      layout: "side",
    },
  ],
  stat: {
    n: "15",
    unit: "张",
    text: "一篇正文只有 2 张结果图的论文，我们为一次组会文献汇报新画的图。",
    note: "2026 年 11 月的一份组会文献汇报，讲 Soter et al. (2025), Developmental Psychology；按交付的那份稿清点。",
  },
} as const;

/**
 * 首页 02：样张横滑（官网v2方案.md H3）。第四轮（Edison 11-19「你别只逮着一个人薅啊，那么多人呢」）：12 张来自 12 个人的稿，
 * 顺序照主窗口定的；首屏那份（IRIS 英文）不再出现。都讲公开论文、都有设计；说明只写论文出处，不写客户是谁。更多在样张页（/samples）。
 */
export const SAMPLES = {
  no: "02",
  eyebrow: "样张",
  h: "都是我们做的，|这里只是一部分。",
  items: [
    { key: "n29", title: "引入：同一个人的两个日子", meta: "组会文献 · 按 Rafiee et al. (2023), Psychoneuroendocrinology" },
    { key: "p24", title: "被试与实验流程", meta: "组会文献 · 按 Nováková et al. (2024), Evolution and Human Behavior" },
    { key: "n33", title: "引入：同一个问题，两种回答", meta: "组会文献 · 按 Castello et al. (2025), Communications Psychology" },
    { key: "n35", title: "BDI/E 认知状态", meta: "课程作业 · 多篇合讲 · 讲 Ma et al. (2026) 等" },
    { key: "n36", title: "行为证据：注意波动呈低频特征", meta: "课程文献汇报 · 按 Yang et al. (2024), Neuropsychologia" },
    { key: "n37", title: "传统交叉滞后结果", meta: "组会文献 · 按 Zhang & Li (2026), Computers in Human Behavior" },
    { key: "n38", title: "暴露：居住绿化的测量", meta: "课程文献汇报 · 按 Sarkar et al. (2018), The Lancet Planetary Health" },
    { key: "n12", title: "替代解释", meta: "组会文献 · 按 Persson et al. (2021), Cognition" },
    { key: "n39", title: "理论框架", meta: "组会文献 · 按 Alekseeva et al. (2026), Strategic Management Journal" },
    { key: "n24", title: "理论整合", meta: "组会 · 据 Dong & Potenza (2014)、Brand et al. (2014) 重画" },
    { key: "n27", title: "研究一：实验流程", meta: "组会文献 · 按 Soter et al. (2025), Developmental Psychology" },
    { key: "p06", title: "数据、模型、验证三层", meta: "文献汇报 · 按 Sha et al. (2026), Translational Psychiatry" },
  ],
} as const;

/** 首页 03–08 各屏的标题（官网v2方案.md H4–H10）。标「我写的」的句子是草稿，等 Edison 改；数字一律从价目接口填 */
export const GOT = {
  no: "03",
  eyebrow: "你会拿到",
  h: "拿到的是一整份。",
  lead: "可编辑的 PPT、逐页讲稿、每处内容标出处，含修改。",
  caption: "一份两篇合读的组会汇报：57 页 PPT 和逐页讲稿（讲 Wang et al. 2022、Cheng et al. 2022）。这里按顺序排出正文 52 页，略去封面、致谢和参考文献页。",
};

export const FLOW = {
  no: "04",
  eyebrow: "怎么交付",
  h: "先看水印版，|满意了再确认收货。",
  // 每一步右边放的真截图（本机起平台、自己造一单截的，生成清单 R7）；没截到的先占位
  shots: [
    { key: "r7Order", slot: "下单页选档那一屏：选汇报时长、材料篇数，右边合计（R7 真截图）" },
    { key: "r7Redeem", slot: "兑换认领页：输入激活码认领订单、上传材料（R7 真截图）" },
    { key: "r7Proof", slot: "交付页：水印版逐页看，某一页下面提修改（R7 真截图）" },
    { key: "r7Final", slot: "确认收货后：最终版 PPT 和讲稿可下载（R7 真截图）" },
  ],
} as const;

/**
 * 付款后的需求引导（平台 docs/任务单/09_需求引导_方案.md，另一个 agent 在做需求卡页面）：Edison 11-19「来付费的人不知道怎么描述需求」。
 * 首页只放一小段让人觉得简单；需求卡页面还没做出来，图位先占着（本机开发才显示），做好后换真截图。
 */
export const BRIEF = {
  h: "不知道怎么描述需求？付款后只要三件事。",
  steps: ["选汇报场合", "挑一份最像你想要的样张", "传材料"],
  after: "我们按你选的出一张需求确认卡，你点「对，开工」我们才开工。",
  slot: "需求卡截图（需求引导页面做好后换真截图）",
};

export const PRICE = {
  no: "05",
  eyebrow: "价目",
  h: "元起，|按讲多久、讲几篇定价。", // 前面接起价
};

export const FEEDBACK = {
  no: "06",
  eyebrow: "用过的人怎么说",
  h: "导师放行，|同学说逻辑清楚。",
  items: [
    { key: "f01", who: "客户转来的导师回复" },
    { key: "f02", who: "客户收到稿以后" },
    { key: "f03", who: "客户收到稿以后" },
  ],
  note: "截图来自客户的聊天记录，头像和名字已隐去。",
} as const;

export const GALLERY = {
  no: "07",
  eyebrow: "科研图库",
  h: "想自己画？|先看好刊怎么画。",
  lead: "心理学好刊里的图，按你要画的找：实验流程、模型图、研究总览，免费检索。",
  // 11-18 换成有设计的图（试次流程、研究总览、干预流程、理论框架、被试流程、机制示意各一张），不放脑电、脑图、热图这类程序直出的图
  items: [
    { key: "g09", kind: "试次流程", journal: "Communications Psychology" },
    { key: "g10", kind: "研究总览", journal: "Current Biology" },
    { key: "g12", kind: "理论框架", journal: "Lancet Child & Adolescent Health" },
    { key: "g11", kind: "干预流程", journal: "Communications Psychology" },
    { key: "g13", kind: "被试流程", journal: "JAMA Psychiatry" },
    { key: "g14", kind: "机制示意", journal: "PNAS" },
  ],
  note: "图的版权归原作者和期刊，每张都写明出处。",
} as const;

export const REFUND_HOME = { no: "08", eyebrow: "退款与售后", h: "规则付款前就写清。" };

export const CLOSING = {
  h: "汇报那天，|照着讲就行。",
  caption: "示意：教室是模型生成的，幕上是我们做的一页（文献汇报第 22 页，按 Zhang et al. (2026) 表 1–3 画的路径图）。",
};

export interface Facts {
  revisions: number;
  days: number;
  refsHours: number;
  pageRule: string;
  revisionPrice: string;
  rushPrice: string;
  rushTiers: string;
  start: string;
}

/** 从价目里拿页面要的几个数；价目还没来时返回 null（页面先不显示带数的句子） */
export function facts(c: ShopCatalog | null): Facts | null {
  if (!c) return null;
  const addon = (k: string) => c.addons.find((a) => a.key === k)?.price ?? "";
  const prices = c.tiers.flatMap((t) => Object.values(t.prices).filter((v): v is string => !!v));
  const start = prices.length ? prices.reduce((a, b) => (Number(b) < Number(a) ? b : a)) : "";
  const rush = c.tiers.filter((t) => t.rush).map((t) => t.name);
  return {
    revisions: c.revisions_included,
    days: c.auto_confirm_days,
    refsHours: c.find_refs_extra_hours,
    pageRule: c.page_rule_text,
    revisionPrice: addon("revision"),
    rushPrice: addon("rush"),
    rushTiers: rush.length ? `${rush.join("、")}档` : "",
    start,
  };
}

// ---------------- 首页 ----------------

export const homeGet = (f: Facts | null) => [
  { title: "可编辑的 PPT（pptx）", text: "按你选的汇报时长做，内容页不超过这一档的上限。" },
  { title: "逐页讲稿", text: "按时长写好，照着能讲。" },
  { title: "内容标出处，APA 第 7 版", text: "内容只用你发来的材料和原文；我们自己归纳的，也标明是归纳。" },
  { title: f ? `含 ${f.revisions} 轮修改` : "含修改", text: "在原材料范围内的改动都算修改。" },
];

export const HOME_STEPS = [
  { title: "付款、认领", text: "在下单页付款后拿到激活码，用它认领订单，再上传材料。" },
  { title: "开工", text: "材料齐了就开工，开工时告诉你大概几点交水印版。" },
  { title: "看水印版、提修改", text: "每页一张完整大小的图片，铺了水印，用来看效果、提修改。" },
  { title: "确认收货", text: "你点「确认收货」后，我们发可编辑的 PPT 和讲稿。" },
];

// ---------------- 交付说明 ----------------

export const GET: { lead: string; text: string }[] = [
  { lead: "可编辑的 PPT（pptx）", text: "，按你选的汇报时长做，内容页不超过这一档的上限（不含封面、目录、过渡页、参考文献、致谢）。" },
  { lead: "逐页讲稿", text: "，按时长写好，照着能讲。" },
  { lead: "内容只用你发来的材料和原文", text: "，每条标出处（APA 第 7 版）；我们自己归纳的，也标明是归纳。" },
  { lead: "原文的图照用", text: "，标明图号；原文没有、光靠文字讲不清的（实验流程、问卷、模型和假设），按心理学好刊的画法画出来。" },
  { lead: "说一下学校", text: "，就用上校徽和配色；也可以套你发来的模板。" },
];

export const how = (f: Facts | null) => [
  { title: "先交水印版", text: "每页一张完整大小的图片，铺了水印，用来看效果、提修改。" },
  { title: f ? `含 ${f.revisions} 轮修改` : "含修改", text: "看完把要改的地方一次说齐，我们改好再交一版。" },
  {
    title: "确认收货",
    text: `你点「确认收货」后，我们发可编辑的 PPT 和讲稿。每次水印版交出后 ${f?.days ?? "几"} 天内没提修改、也没确认，系统自动确认收货。`,
  },
];

export const notes = (f: Facts | null): { lead: string; text: string }[] => [
  { lead: "先认领，再交材料：", text: "付款后用激活码认领订单，再上传材料。材料齐了就开工，开工时告诉你大概几点交水印版。" },
  { lead: "时间：", text: "从开工算，在这一档的标准时限内交水印版。排队、你看稿和改稿的时间不算在内。" },
  {
    lead: "修改：",
    text: `含 ${f?.revisions ?? ""} 轮，请一次说齐。想再改一轮，加购「再改一轮」，${f?.revisionPrice ?? ""} 元一轮。在原材料范围内的改动都算修改；换题目、加新材料、改汇报时长，算新的一单。`,
  },
  {
    lead: "加急：",
    text: `只有${f?.rushTiers ?? ""}、材料齐全时能加，每天名额有限；没在加急时限内交，退加急的 ${f?.rushPrice ?? ""} 元。`,
  },
  {
    lead: "退款：",
    text: "这是按你的材料单独做的定制服务，不适用七天无理由退款；开工前想撤单可以退，开始制作后不支持仅退款。不满意先告诉我们哪里要改。",
  },
  {
    lead: "不接：",
    text: "只有问卷原始数据、访谈录音或逐字稿，要先做数据分析或编码才能汇报的；写论文、改论文、数据分析、建模也不接。用问卷、访谈方法做的研究，论文和开题汇报照常接。",
  },
  { lead: "", text: "你发来的材料、数据和草稿不公开，也不拿去当示例。我们只做汇报，不写论文、不编数据；上台前请自己过一遍，按老师的要求微调。" },
  { lead: "AI 辅助：", text: "我们用 AI 辅助制作，经审读、检查后交付。请按学校和导师对 AI 使用的要求注明，详见免责声明。" },
];

// ---------------- 退款与售后 ----------------

export const REFUND_LEAD = "这是按你的材料单独做的定制服务。";

export const refund = (f: Facts | null) => [
  { term: "开工前", text: "开工前想撤单，可以退款。" },
  {
    term: "开始制作后",
    text: `开始制作后不支持仅退款。不满意，先告诉我们哪里要改：基础价含 ${f?.revisions ?? ""} 轮修改，改完再交一版水印版，你确认后我们发最终版。`,
  },
  { term: "加急", text: "加了加急但没在加急时限内交出水印版的，退还加急费。" },
  {
    term: "确认收货",
    text: `你点「确认收货」后，我们发可编辑的 PPT 和讲稿；水印版交出后 ${f?.days ?? ""} 天内没提修改、也没确认，系统自动确认收货。`,
  },
];

// ---------------- 价目页的加购说明（价格从价目接口来） ----------------

export function addonText(key: string, f: Facts | null, note: string): string {
  if (key === "rush") return `只对${f?.rushTiers ?? ""}、材料齐全的订单开放，每天名额有限；没在加急时限内交水印版，退还加急费。`;
  if (key === "revision") return `基础价含 ${f?.revisions ?? ""} 轮修改；还想再改，每多一轮加购一次。`;
  if (key === "find_refs") return `你只给主题或几篇，我们帮你找原文、整理脉络；按 1 篇的价算，找到几篇都含在里面；标准时限加 ${f?.refsHours ?? ""} 小时，不开放加急。`;
  return note;
}
