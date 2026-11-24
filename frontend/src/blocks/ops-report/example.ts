import { SAMPLE_SETTINGS } from "@/blocks/ops-settings/example";
import { defineBlockDemo } from "@/lib/blocks";
import type { ReportPreview } from "@/lib/ops-types";

import { OpsReport } from "./OpsReport";

// 示意数据，不是真数据
const link = "https://psyppt.pilipala.zj.cn/admin/ops";
export const SAMPLE_PREVIEW: ReportPreview = {
  day: "2026-11-17",
  problems: 0,
  message: {
    title: "【日报】11-17（周二）网站一切正常",
    level: "info",
    text: "",
    sections: [
      { title: "有没有要你处理的问题", lines: [{ text: "一切正常，没有要你处理的。", link: "" }] },
      { title: "昨天网站运行", lines: [
        { text: "可用性 99.93%（1440 分钟里 1439 分钟在线）", link: "" },
        { text: "请求 2,310 次，出错（5xx）2 次，成功率 99.91%；一半请求在 21 毫秒内，95% 在 190 毫秒内", link: `${link}?tab=errors` },
        { text: "水印出图：昨天出了 4 版，现在在排 0 版", link: "" },
      ] },
      { title: "昨天业务数据", lines: [{ text: "访问（独立访客） 102；下单（自有网页） 6；付款（全部渠道） 5；认领 5；交水印版 4；确认收货 3；退款作废 0；开票申请 1", link: "" }] },
      { title: "新收集的建议", lines: [
        { text: "昨天新收到 3 条：标签反馈 1、提需求 1、投图 0、网站意见 1", link: "" },
        { text: "提需求：想要一张交叉滞后模型的图", link: "https://psyppt.pilipala.zj.cn/admin/figures/requests" },
      ] },
      { title: "待处理事项", lines: [{ text: "待开票 1 条：单号 00137 39.80", link: "https://psyppt.pilipala.zj.cn/admin/invoices" }] },
    ],
  },
};

const ok = async () => undefined;

export default defineBlockDemo({
  block: "ops-report",
  title: "后台：飞书汇报",
  order: 98,
  component: OpsReport,
  examples: [
    { name: "没配机器人", props: { settings: SAMPLE_SETTINGS, preview: SAMPLE_PREVIEW, onSave: ok, onTestSend: ok, onSendNow: ok, onRefreshPreview: () => undefined } },
    {
      name: "配好了",
      props: {
        settings: { ...SAMPLE_SETTINGS, sender: { sender: "feishu_webhook", label: "飞书群机器人", configured: true, source: "文件 /root/xueshu-platform/secrets/feishu_ops_webhook", signed: true, mode: "auto" } },
        preview: SAMPLE_PREVIEW, onSave: ok, onTestSend: ok, onSendNow: ok, onRefreshPreview: () => undefined,
      },
    },
  ],
});
