/**
 * 协议类三份文件的元信息；正文在同目录的 .md（律师、Edison 能直接改）。
 * 改了正文要改 lib/site-pages.ts 的 POLICY_VERSIONS：下单页记同意时记的是它（用户协议、隐私政策），更新日志也记一条。
 * 每份都标「草稿，待法务或财务确认」（LegalDoc 自动加）；open 列这一版还没定的地方。
 */
import type { LegalDocData } from "@/blocks/legal-doc";
import { POLICY_VERSIONS } from "@/lib/site-pages";

import disclaimerMd from "./disclaimer.md?raw";
import privacyMd from "./privacy.md?raw";
import termsMd from "./terms.md?raw";

export const TERMS: LegalDocData = {
  title: "用户协议",
  version: POLICY_VERSIONS.terms,
  lead: "关于下单、付款、交付、修改、退款、材料与成品的权利、学术规范等事项，你与我们之间的约定。",
  open: [
    "争议管辖法院、赔偿上限等条款，待律师确认。",
    "「交付内容与约定明显不符」的认定标准和退款比例，待确认。",
    "平台订单（闲鱼、小红书等）与本协议的衔接方式，待细化；平台规则以平台为准。",
  ],
  basis:
    "底稿：GitHub 服务条款（github/site-policy，CC0-1.0）的章节结构；必须写明、不能写的事项按《消费者权益保护法》第二十六条、第二十八条，《电子商务法》第二十四条、第四十九条；服务规则沿用本站价目、交付说明、退款与售后。",
  markdown: termsMd,
};

export const PRIVACY: LegalDocData = {
  title: "隐私政策",
  version: POLICY_VERSIONS.privacy,
  lead: "说明我们收集哪些信息、用途、委托哪些第三方处理（含 AI 模型和数据出境）、保存期限，以及你如何查阅和删除。",
  open: [
    "材料、成品和聊天记录的保存期限（目前写的是订单完成后 180 天）待确认，到期自动删除功能尚未上线。",
    "制作所用 AI 服务账号的「数据用于模型训练」设置、第三方的保存期限，待核实后补充。",
    "未发表稿件交由第三方模型处理的规则，待确认。",
    "接单助手所用的模型接口服务商、服务器和文件存储服务商，以正式上线时为准。",
    "手机号、微信用户标识的保存期限（目前写的是到注销账号或要求删除为止），待法务确认。",
    "取消关注服务号即删除微信用户标识的做法（按微信开放文档的要求），待法务确认是否需要另行告知。",
  ],
  basis:
    "底稿：国家标准 GB/T 35273—2020《信息安全技术 个人信息安全规范》附录 D「个人信息保护政策模板」（结构和措辞照它改写，按我们的服务填）；出境告知的几项按《个人信息保护法》第三十九条列。",
  markdown: privacyMd,
};

export const DISCLAIMER: LegalDocData = {
  title: "免责声明",
  version: POLICY_VERSIONS.disclaimer,
  lead: "本站服务采用 AI 辅助制作，请按学校和导师对 AI 使用的要求注明；内容以你提供的材料为准，上台前请自行核对。",
  open: ["注明 AI 辅助的参考写法，待熟悉高校相关规定的人士审定。"],
  basis: "底稿：本站交付说明、用户协议里关于 AI 辅助、引用和责任的条款。",
  markdown: disclaimerMd,
};
