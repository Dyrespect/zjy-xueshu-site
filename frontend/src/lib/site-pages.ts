/**
 * 官网（psyppt 站）的页面清单：路径、标题、一句描述、在页脚哪一组。页头导航、页脚、网站地图页、每页的 <title> 和描述都从这里来。
 * sitemap.xml 也从这份出（构建时 vite-plugin-sitemap，见 vite.config.ts）；scripts/check.py 规矩 18 查每页都有路由、站内链接都通。
 * 加一页：这里加一行 + 在 pages/site/routes.tsx（或那一页自己的 routes.tsx）挂路由。
 */

export const SITE_NAME = "心理学汇报 PPT 定制";

/** 用户协议、隐私政策当前版本（日期）。改了 pages/site/legal/ 里的正文就改这里；下单页记同意时记的就是它 */
export const POLICY_VERSIONS = { terms: "2026-11-18", privacy: "2026-11-19", disclaimer: "2026-11-18" } as const;
export const SITE_OWNER_SHORT = "PsyEngine"; // 对客人的品牌是 PsyEngine；竹涧云只出现在页脚、协议、发票这些法定位置（Edison 11-19）

export type SiteGroup = "服务" | "图库" | "关于" | "协议";

export interface SitePage {
  path: string;
  title: string;
  /** <meta name="description">，也是网站地图页上那一句 */
  description: string;
  group: SiteGroup;
}

export const SITE_PAGES: SitePage[] = [
  { path: "/", title: "首页", group: "服务", description: "心理学研究生和博士生的汇报 PPT 定制：可编辑 pptx、逐页讲稿、内容标出处、含一轮修改。" },
  { path: "/samples", title: "样张", group: "服务", description: "我们做的汇报页，按实验流程、模型、研究设计、分析流程等页型分组，每页写明按哪篇公开论文制作；另有原文和汇报页的对照。" },
  { path: "/price", title: "价目", group: "服务", description: "按汇报时长选档、按材料篇数定价，含一轮修改；加购只有加急、再改一轮、帮我找文献三样。" },
  { path: "/service", title: "交付说明", group: "服务", description: "交付内容、交付方式（先交水印版、含一轮修改、确认收货后发最终版）和不接的情况，下单前都写在这里。" },
  { path: "/refund", title: "退款与售后", group: "服务", description: "定制服务：开工前可以撤单退款，开始制作后不支持仅退款，不满意先修改；加急未按时交付的，退还加急费。" },
  { path: "/order", title: "下单", group: "服务", description: "选择汇报时长和材料篇数，确认价格，付款后用激活码认领订单、上传材料。" },
  { path: "/help", title: "帮助中心", group: "服务", description: "常见问题：价格、时间、修改、退款、材料、发票、AI 使用，一页查完。" },
  // 图库这一组的页归科研绘图聚人模块（pages/figures/），这里只列出来给页头页脚、网站地图、sitemap.xml 用
  { path: "/tuku", title: "科研图库", group: "图库", description: "心理学好刊里的图，按你要画的找：实验流程、模型图、结果图，免费检索。" },
  { path: "/request", title: "提需求", group: "图库", description: "库里没找到想要的图，告诉我们你要画什么。" },
  { path: "/submit", title: "投图", group: "图库", description: "推荐好刊里画得好的图，审核后收录进图库。" },
  { path: "/plugin", title: "把图库装进你的 AI", group: "图库", description: "在 AI 工具里直接检索心理学科研图库。" },
  { path: "/copyright", title: "版权问题", group: "图库", description: "图片版权归原作者和期刊；版权方可以在这里申请下架。" },
  { path: "/about", title: "关于我们", group: "关于", description: "杭州竹涧云科技有限公司：我们做什么、怎么做，主体信息、备案信息和联系方式。" },
  { path: "/license", title: "营业执照", group: "关于", description: "按电子商务法第十五条公示的营业执照：名称、统一社会信用代码、类型、法定代表人、住所、成立日期、登记机关和执照电子版。" },
  { path: "/contact", title: "联系我们", group: "关于", description: "联系方式，售后和投诉的处理流程与答复时限，个人信息的查阅、更正、删除渠道。" },
  { path: "/changelog", title: "更新日志", group: "关于", description: "本站功能和规则的更新记录。" },
  { path: "/status", title: "运行状态", group: "关于", description: "网站服务当前是否正常。" },
  { path: "/sitemap", title: "网站地图", group: "关于", description: "本站所有对外页面的列表。" },
  { path: "/terms", title: "用户协议", group: "协议", description: "下单、付款、交付、修改、退款、材料和成品的权利、学术规范等双方约定（草稿）。" },
  { path: "/privacy", title: "隐私政策", group: "协议", description: "收集哪些信息、用途、委托哪些第三方处理（含 AI 模型和数据出境）、保存期限、如何查阅和删除（草稿）。" },
  { path: "/disclaimer", title: "免责声明", group: "协议", description: "AI 辅助制作，请按学校和导师对 AI 使用的要求注明；内容以你的材料为准，上台前请自行核对（草稿）。" },
];

/** 页头的主导航（顺序就是页面上的顺序）；「下单」是右边单独的按钮 */
export const MAIN_NAV: string[] = ["/samples", "/price", "/service", "/refund", "/tuku", "/about"];
export const ORDER_PATH = "/order";
/** 营业执照公示页（《电子商务法》第十五条：首页显著位置持续公示营业执照信息或链接标识）：页脚公司那一块也链过去 */
export const LICENSE_PATH = "/license";
export const SITE_GROUPS: SiteGroup[] = ["服务", "图库", "关于", "协议"];

export function sitePage(path: string): SitePage | undefined {
  return SITE_PAGES.find((p) => p.path === path);
}

/** 浏览器标签上的标题：首页「站名 · PsyEngine」，内页「页名 · 站名 · PsyEngine」 */
export function siteTitle(title: string, path = ""): string {
  return path === "/" || !title ? `${SITE_NAME} · ${SITE_OWNER_SHORT}` : `${title} · ${SITE_NAME} · ${SITE_OWNER_SHORT}`;
}
