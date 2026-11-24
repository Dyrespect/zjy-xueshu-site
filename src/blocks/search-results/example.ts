import { defineBlockDemo } from "@/lib/blocks";
import type { SearchResult } from "@/lib/figures-types";

import { EXAMPLE_CARDS } from "../figure-card/example-data";
import { SearchResults, type SearchResultsProps } from "./SearchResults";

const types = [
  { code: "D1", name: "实验设计" },
  { code: "D2", name: "试次流程" },
  { code: "D3", name: "测量时间线" },
  { code: "W2", name: "假设模型与理论框架" },
];

const result: SearchResult = {
  search_id: 1,
  query: "被试内实验的试次流程",
  words: [
    { word: "被试内", count: 750 },
    { word: "实验", count: 2404 },
    { word: "试次流程", count: 230 },
  ],
  zero_words: [],
  guess: { code: "D2", name: "试次流程" },
  code: "D2",
  code_name: "试次流程",
  overridden: false,
  total: 8,
  groups: [
    { key: "close", title: "最像你要画的", learn: "看整体怎么摆、放了哪些东西", cards: EXAMPLE_CARDS.slice(0, 5) },
    { key: "method:被试内", title: "同样用了「被试内」的研究", learn: "学这个领域、这种方法的惯例", cards: EXAMPLE_CARDS.slice(5) },
  ],
};

const base: Omit<SearchResultsProps, "result"> = {
  types,
  cta: { siteUrl: "https://www.example.org/", orderUrl: "/order?from=tuku_results" },
  onChangeType: () => undefined,
  hrefFor: (c) => `/figure/${c.id}`,
  onRequest: () => undefined,
};

export default defineBlockDemo({
  block: "search-results",
  title: "搜索结果",
  order: 30,
  component: SearchResults,
  examples: [
    { name: "猜出图型、按路分组", props: { ...base, result } },
    {
      name: "库里没有某个词",
      props: {
        ...base,
        result: {
          ...result,
          query: "催眠诱导的流程",
          words: [
            { word: "催眠诱导", count: 0 },
            { word: "流程", count: 1414 },
          ],
          zero_words: ["催眠诱导"],
          groups: [
            {
              key: "extra:去掉",
              title: "去掉「催眠诱导」再找",
              learn: "去掉库里没有的词，用其余的词找",
              cards: [
                { id: 16205, thumb_url: "/api/figures/16205/thumb", title: "实验2两种编码及即时与最终测验的流程", journal: "心理学报", year: "2024", tier: "学科好刊", type_code: "D2", type_name: "试次流程" },
                { id: 15619, thumb_url: "/api/figures/15619/thumb", title: "三种材料呈现下学到达标的实验流程", journal: "心理学报", year: "2023", tier: "学科好刊", type_code: "D2", type_name: "试次流程" },
                { id: 557, thumb_url: "/api/figures/557/thumb", title: "抑郁参照点假设与觅食竞价流程", journal: "PNAS", year: "2026", tier: "正刊", type_code: "D2", type_name: "试次流程" },
                { id: 17167, thumb_url: "/api/figures/17167/thumb", title: "实验1点探测任务的试次流程", journal: "心理学报", year: "2026", tier: "学科好刊", type_code: "D2", type_name: "试次流程" },
              ],
            },
          ],
          total: 4,
        },
      },
    },
    { name: "一张都没找到", props: { ...base, result: { ...result, query: "箱庭疗法", guess: null, code: "任意", code_name: "不限图型", groups: [], total: 0 } } },
    { name: "加载中", props: { ...base, result: null, loading: true } },
  ],
});
