/**
 * 样张页（/samples，官网v2方案.md 第四节）：按汇报场合分组放我们做的页，再放全部「原文这样写 → 我们画成」。
 * 都讲公开论文（Edison 11-18：「所有组会汇报都可以拿来直接用，只要不是他们自己的研究」）；客户自己的开题、中期一页不放；
 * 说明只写论文出处，不写客户是谁。图和 alt 在 lib/site-media.ts。
 * 程序直出、没有设计的页（整页头皮地形图这类）不放。
 */
import type { MediaKey } from "@/lib/site-media";

export interface SampleItem {
  key: MediaKey;
  title: string;
  source: string;
}

export interface SampleGroup {
  id: string;
  title: string;
  lead: string;
  items: SampleItem[];
}

/**
 * 第四轮（Edison 11-19「你别只逮着一个人薅啊，那么多人呢」）：按页型分组；每份稿最多 3 页（连同页尾对照里用到的页一起算），尽量多人。
 * 西西那份是课程作业（多篇合讲），单列一组；它第三块 CPsyCoun 复现是客户自己的工作，一页不放。
 */
export const SAMPLE_GROUPS: SampleGroup[] = [
  {
    id: "procedure",
    title: "实验范式与流程",
    lead: "原文几段字写的试次、任务和流程，画成一张看得懂的图，时长、试次数照原文标。",
    items: [
      { key: "n16", title: "Setup and Trial Procedure", source: "Park (2018), Developmental Cognitive Neuroscience" },
      { key: "n31", title: "情绪识别任务", source: "Rafiee et al. (2023), Psychoneuroendocrinology" },
      { key: "p24", title: "被试与实验流程", source: "Nováková et al. (2024), Evolution and Human Behavior" },
      { key: "n34", title: "共同的实验流程", source: "Castello et al. (2025), Communications Psychology" },
      { key: "n27", title: "研究一：实验流程", source: "Soter et al. (2025), Developmental Psychology" },
      { key: "n07", title: "实验范式：点探测任务", source: "Liu et al. (2026), Computers in Human Behavior" },
      { key: "p13", title: "安全信号学习试次流程", source: "Odriozola & Gee (2021), American Journal of Psychiatry" },
      { key: "p23", title: "独裁者博弈三种范式", source: "Nováková et al. (2024), Evolution and Human Behavior" },
    ],
  },
  {
    id: "model",
    title: "模型与理论框架",
    lead: "理论和模型画成一张图，读法写在旁边；原文的图翻译重绘，原文没画的按文字画出来。",
    items: [
      { key: "n08", title: "网络游戏障碍的三系统模型", source: "据 Wei et al. (2017), Frontiers in Psychiatry 图 1 重画" },
      { key: "n24", title: "理论整合", source: "据 Dong & Potenza (2014)、Brand et al. (2014) 重画" },
      { key: "n39", title: "理论框架", source: "Alekseeva et al. (2026), Strategic Management Journal" },
      { key: "n32", title: "皮质醇与双激素假说", source: "Nováková et al. (2024), Evolution and Human Behavior" },
      { key: "n11", title: "完整模型图", source: "Castello et al. (2025), Communications Psychology" },
      { key: "p14", title: "发育回路模型", source: "Odriozola & Gee (2021), American Journal of Psychiatry" },
      { key: "p09", title: "主要结论路径图", source: "Zhang et al. (2026), Nature Human Behaviour，按表 1–3 画" },
      { key: "n12", title: "替代解释", source: "Persson et al. (2021), Cognition" },
    ],
  },
  {
    id: "design",
    title: "研究思路与设计",
    lead: "研究问题、设计和测量时间线，一页摆清楚，听的人知道后面每一页在回答什么。",
    items: [
      { key: "n26", title: "研究一：实验设计", source: "Soter et al. (2025), Developmental Psychology" },
      { key: "n14", title: "被试与追踪设计", source: "Zhang & Li (2026), Computers in Human Behavior" },
      { key: "n15", title: "研究设计：暴露、结局和混杂", source: "Sarkar et al. (2018), The Lancet Planetary Health" },
      { key: "n30", title: "研究空白与假设", source: "Rafiee et al. (2023), Psychoneuroendocrinology" },
      { key: "p06", title: "数据、模型、验证三层", source: "Sha et al. (2026), Translational Psychiatry" },
      { key: "p12", title: "研究思路与技术路线", source: "Jiao et al. (2026), Nature Mental Health" },
      { key: "p15", title: "先检验差异再缩小差异", source: "Huang et al. (2026), npj Digital Medicine" },
      { key: "p01", title: "研究思路与技术路线（示范稿）", source: "改编自 Confer et al. (2025), Nature Communications" },
    ],
  },
  {
    id: "analysis",
    title: "测量与分析流程",
    lead: "测量怎么做、数据怎么处理，按步骤画出来，参数写在每一步下面。",
    items: [
      { key: "n19", title: "EEG Processing Pipeline", source: "Park (2018), Developmental Cognitive Neuroscience" },
      { key: "n18", title: "Stimulus Space", source: "Park (2018), Developmental Cognitive Neuroscience" },
      { key: "n09", title: "信号处理与脑间同步的计算", source: "Cheng et al. (2022), Social Cognitive and Affective Neuroscience" },
      { key: "n10", title: "两篇研究的设计对比", source: "Wang et al. (2022), NeuroImage；Cheng et al. (2022), SCAN" },
      { key: "n38", title: "暴露：居住绿化的测量", source: "Sarkar et al. (2018), The Lancet Planetary Health" },
      { key: "n36", title: "行为证据：注意波动呈低频特征", source: "Yang et al. (2024), Neuropsychologia" },
    ],
  },
  {
    id: "intro-result",
    title: "引入与结果解读",
    lead: "开头用一个具体的场景把问题引出来；结果页只读要读的那几条，结论写在标题上。",
    items: [
      { key: "n29", title: "引入：同一个人的两个日子", source: "Rafiee et al. (2023), Psychoneuroendocrinology" },
      { key: "n33", title: "引入：同一个问题，两种回答", source: "Castello et al. (2025), Communications Psychology" },
      { key: "n37", title: "传统交叉滞后结果", source: "Zhang & Li (2026), Computers in Human Behavior" },
      { key: "p11", title: "作者团队与研究脉络", source: "Zhang et al. (2026), Nature Human Behaviour" },
      { key: "p07", title: "年龄就是输入", source: "Sha et al. (2026), Translational Psychiatry" },
      { key: "p03", title: "研究一的结果（示范稿）", source: "改编自 Confer et al. (2025), Nature Communications" },
    ],
  },
  {
    id: "multi",
    title: "多篇合讲 / 课程作业",
    lead: "几篇论文合在一次汇报里讲：每篇的核心概念和模型结构各画一页。",
    items: [
      { key: "n35", title: "BDI/E 认知状态", source: "Ma et al. (2026), arXiv 预印本" },
      { key: "n40", title: "CogWM 模型结构", source: "Ma et al. (2026), arXiv 预印本" },
      { key: "n41", title: "EmWorld 模型结构", source: "Wang et al. (2026), ICML" },
    ],
  },
];

/** 样张页底部的对照组（首页放的是英文原图两组，这里是另外五组）。原文截图是 11-01 发帖时裁的、11-18 盘点出的 */
export const SAMPLE_COMPARES: { original: MediaKey; result: MediaKey; originalLabel: string; resultLabel: string; caption: string; source: string; layout: "side" | "stack" }[] = [
  {
    original: "y02",
    result: "p05",
    originalLabel: "原文 · Sha et al. (2026) 表 2",
    resultLabel: "汇报页 · 文献汇报第 15 页",
    caption: "原文表 2 最后一行是作者的模型，阳性预测值 .776；放到真实的 5.2% 病例占比里，被标出的人约三成真是病例。",
    source: "Sha et al. (2026), Translational Psychiatry，表 2。",
    layout: "stack",
  },
  {
    original: "y01",
    result: "p02",
    originalLabel: "原文 · Confer et al. (2025) 方法部分",
    resultLabel: "汇报页 · 中期示范稿第 5 页",
    caption: "三段英文写的分组、十个盒子的顺序、每开一盒等 30 秒，画成一张实验流程。",
    source: "Confer et al. (2025), Nature Communications，方法部分。",
    layout: "side",
  },
  {
    original: "y03",
    result: "p22",
    originalLabel: "原文 · Soter et al. (2025) 被试部分",
    resultLabel: "汇报页 · 组会文献汇报第 17 页",
    caption: "被试段落画成两个研究的筛选流程图，每一步排除多少人看得见。",
    source: "Soter et al. (2025), Developmental Psychology，被试部分。",
    layout: "side",
  },
  {
    original: "y04",
    result: "n27",
    originalLabel: "原文 · Soter et al. (2025) 流程部分",
    resultLabel: "汇报页 · 组会文献汇报第 21 页",
    caption: "英文问卷流程画成一条时间线和一张表。",
    source: "Soter et al. (2025), Developmental Psychology，流程部分。",
    layout: "side",
  },
  {
    original: "y05",
    result: "p08",
    originalLabel: "原文 · Zhang et al. (2026) 报告摘要",
    resultLabel: "汇报页 · 文献汇报第 9 页",
    caption: "报告摘要里五行字的数据收集过程，画成四步流程。",
    source: "Zhang et al. (2026), Nature Human Behaviour，Reporting Summary。",
    layout: "stack",
  },
];
