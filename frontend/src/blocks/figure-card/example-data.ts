import type { FigureCard, FigureDetail } from "@/lib/figures-types";

/** 陈列页用的示例：库里真实的几张图（搜「被试内实验的试次流程」排在前面的） */
export const EXAMPLE_CARDS: FigureCard[] = [
  { id: 16712, thumb_url: "/api/figures/16712/thumb", title: "实验1b两次注视变化的试次流程", journal: "心理学报", year: "2025", tier: "学科好刊", type_code: "D2", type_name: "试次流程" },
  { id: 17006, thumb_url: "/api/figures/17006/thumb", title: "为自己或为朋友赢钱奖赏的试次流程", journal: "心理学报", year: "2026", tier: "学科好刊", type_code: "D2", type_name: "试次流程" },
  { id: 14589, thumb_url: "/api/figures/14589/thumb", title: "视觉搜索中重复分心物的试次流程", journal: "Psychophysiology", year: "2026", tier: "学科好刊", type_code: "D2", type_name: "试次流程" },
  { id: 14825, thumb_url: "/api/figures/14825/thumb", title: "汉字适应范式的材料与试次流程", journal: "心理学报", year: "2021", tier: "学科好刊", type_code: "D2", type_name: "试次流程" },
  { id: 15003, thumb_url: "/api/figures/15003/thumb", title: "实验1人名圈内外判断的试次流程", journal: "心理学报", year: "2022", tier: "学科好刊", type_code: "D2", type_name: "试次流程" },
  { id: 16721, thumb_url: "/api/figures/16721/thumb", title: "赌博试次流程与连续输赢反馈安排", journal: "心理学报", year: "2025", tier: "学科好刊", type_code: "D2", type_name: "试次流程" },
  { id: 16805, thumb_url: "/api/figures/16805/thumb", title: "实验3第一人称接收任务的试次流程", journal: "心理学报", year: "2025", tier: "学科好刊", type_code: "D2", type_name: "试次流程" },
  { id: 16812, thumb_url: "/api/figures/16812/thumb", title: "实验2生物运动Flanker的试次流程", journal: "心理学报", year: "2025", tier: "学科好刊", type_code: "D2", type_name: "试次流程" },
];

export const EXAMPLE_DETAIL: FigureDetail = {
  ...EXAMPLE_CARDS[0],
  preview_url: "/api/figures/16712/preview",
  paper_title: "持续性视觉注意对视觉工作记忆项目优先加工的影响",
  authors: "",
  doi: "10.3724/SP.J.1041.2025.0191",
  link: "https://doi.org/10.3724/SP.J.1041.2025.0191",
  caption: "实验1b流程示意图　注: 前线索上为提示性线索, 下为中性线索; 视觉注意任务上为注视点无变化, 下为注视点发生变化。",
  cite: "持续性视觉注意对视觉工作记忆项目优先加工的影响, 2025, 心理学报, doi:10.3724/SP.J.1041.2025.0191",
  types: [{ code: "D2", name: "试次流程" }],
  tags: [
    { label: "研究的情况", words: ["被试内", "行为实验"] },
    { label: "方法范式", words: ["视觉工作记忆", "VWM", "言语抑制"] },
    { label: "手段", words: ["行为实验"] },
    { label: "画面上有什么", words: ["灰色屏幕", "注视十字", "彩色图形", "箭头线索", "时间标注"] },
    { label: "结构", words: ["试次流程", "时间轴"] },
  ],
};
