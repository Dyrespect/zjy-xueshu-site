import { defineBlockDemo } from "@/lib/blocks";
import type { MaterialsGuideView } from "@/lib/shop-types";

import { MaterialsGuide } from "./MaterialsGuide";

// 示例数据照订单中枢设置的默认资料清单（真页面从 /api/shop/catalog 的 materials 读，不写死）
const guide: MaterialsGuideView = {
  "title": "下单前准备好这些",
  "lead": "按你的场合准备。必须发的齐了才开工；有的话更好的几样，能让 PPT 更贴你们组和老师的要求。",
  "must_title": "必须发的",
  "nice_title": "有的话更好",
  "common_title": "每个场合都要说一声",
  "rule": "资料齐了才开工，时限从开工那会儿算，不是从付款算。",
  "common": [
    {
      "text": "讲几分钟",
      "use": "定页数和详略",
      "required": true
    },
    {
      "text": "哪天汇报",
      "use": "排期，看赶不赶得上",
      "required": true
    },
    {
      "text": "学校名",
      "use": "放校徽和配色",
      "required": false
    }
  ],
  "occasions": [
    {
      "key": "组会文献",
      "name": "组会读文献",
      "must": [
        {
          "text": "要讲的论文 PDF（几篇发几篇）",
          "use": "PPT 的内容全从它来"
        }
      ],
      "nice": [
        {
          "text": "组里或学校的 PPT 模板",
          "use": "有就照它做，没有就用学校配色"
        },
        {
          "text": "老师或组里的要求（固定结构、页数）",
          "use": "照着排结构、定页数"
        },
        {
          "text": "以前被老师问过的问题",
          "use": "讲稿里提前备好怎么答"
        },
        {
          "text": "补充材料",
          "use": "正文没写透的方法和结果从这里补"
        }
      ]
    },
    {
      "key": "课程文献",
      "name": "课程汇报",
      "must": [
        {
          "text": "要讲的论文 PDF（几篇发几篇）",
          "use": "PPT 的内容全从它来"
        }
      ],
      "nice": [
        {
          "text": "老师布置的要求",
          "use": "照着定结构和重点"
        },
        {
          "text": "PPT 模板",
          "use": "有就照它做，没有就用学校配色"
        }
      ]
    },
    {
      "key": "开题",
      "name": "开题",
      "must": [
        {
          "text": "开题报告（或开题 PPT 初稿）",
          "use": "研究问题、方法、预期都从这里出"
        }
      ],
      "nice": [
        {
          "text": "学校模板",
          "use": "有就照它做，没有就用学校配色"
        },
        {
          "text": "老师意见",
          "use": "老师提过的地方在 PPT 里改到位"
        },
        {
          "text": "实验材料",
          "use": "照着画实验流程，讲清怎么测"
        }
      ]
    },
    {
      "key": "中期",
      "name": "中期",
      "must": [
        {
          "text": "开题报告（或开题 PPT）",
          "use": "交代研究问题和当初的计划"
        },
        {
          "text": "现在的进展（文稿、PPT、跑出来的结果图都行）",
          "use": "讲做了什么、结果怎样、接下来做什么"
        }
      ],
      "nice": [
        {
          "text": "学校模板",
          "use": "有就照它做，没有就用学校配色"
        },
        {
          "text": "实验材料",
          "use": "照着画实验流程"
        },
        {
          "text": "分析好的结果图",
          "use": "结果页直接照它讲"
        }
      ]
    },
    {
      "key": "答辩",
      "name": "答辩",
      "must": [
        {
          "text": "毕业论文全文（Word 也行）",
          "use": "PPT 的内容全从它来"
        }
      ],
      "nice": [
        {
          "text": "学校模板",
          "use": "有就照它做，没有就用学校配色"
        },
        {
          "text": "预答辩意见",
          "use": "评委提过的地方重点讲清，讲稿里备好怎么答"
        }
      ]
    },
    {
      "key": "会议",
      "name": "会议报告",
      "must": [
        {
          "text": "论文稿或摘要",
          "use": "PPT 的内容全从它来"
        }
      ],
      "nice": [
        {
          "text": "结果图",
          "use": "结果页直接照它讲"
        },
        {
          "text": "会议对报告的要求（时长、页数、模板）",
          "use": "照着卡时长和版式"
        }
      ]
    }
  ]
};

export default defineBlockDemo({
  block: "materials-guide",
  title: "下单前准备好这些（按场合）",
  order: 9,
  component: MaterialsGuide,
  examples: [
    { name: "默认（组会读文献）", props: { guide } },
    { name: "先看中期、紧凑", props: { guide, initial: "中期", compact: true } },
  ],
});
