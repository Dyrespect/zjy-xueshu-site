import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";

export interface OrderPaidProps {
  code: string;
  /** 去哪交码（兑换页 / 网页聊天） */
  redeemUrl: string;
  /** 付了什么，一行（自有网页有；平台固定链接页可不给） */
  summary?: string;
  /** 付了多少（分）；不给就不显示 */
  paidFen?: number;
  title?: string;
}

/** 付完了：激活码 + 复制 + 下一步去哪交码。只吃 props。 */
export function OrderPaid({ code, redeemUrl, summary, paidFen, title = "付款成功" }: OrderPaidProps) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(code).then(
      () => {
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1800);
      },
      () => undefined,
    );
  };
  const steps = [
    "复制上面的激活码（截个图也行，丢了找不回来要等负责人查）。",
    "点下面的按钮打开网页聊天，把激活码发给助手，认领这一单。",
    "助手会告诉你要交哪些材料；材料齐了就开工，开工时告诉你大概几点交水印版。",
  ];
  return (
    <div className="mx-auto flex max-w-xl flex-col gap-6 px-4 py-10 sm:px-6">
      <div className="flex flex-col gap-1">
        <h1 className="font-display text-3xl leading-tight font-bold tracking-wide text-foreground">{title}</h1>
        {summary ? (
          <p className="text-sm text-body">
            {summary}
            {paidFen ? ` · 实付 ${Math.floor(paidFen / 100)}.${String(paidFen % 100).padStart(2, "0")} 元` : ""}
          </p>
        ) : null}
      </div>
      <div className="flex flex-col items-center gap-3 rounded-lg border px-5 py-7">
        <span className="text-xs text-muted-foreground">你的激活码</span>
        <span className="font-mono text-2xl font-semibold tracking-wider text-foreground sm:text-3xl" data-testid="activation-code">
          {code}
        </span>
        <Button variant="outline" size="sm" onClick={copy}>
          {copied ? <Check /> : <Copy />}
          {copied ? "复制好了" : "复制激活码"}
        </Button>
      </div>
      <ol className="flex flex-col gap-2.5">
        {steps.map((s, i) => (
          <li key={s} className="flex gap-3 text-sm leading-relaxed text-body">
            <span className="mt-0.5 w-5 shrink-0 text-xs font-medium text-muted-foreground tabular-nums">0{i + 1}</span>
            <span>{s}</span>
          </li>
        ))}
      </ol>
      <Button asChild size="lg" className="h-11 text-[15px]">
        <a href={redeemUrl}>去交码，认领这一单</a>
      </Button>
    </div>
  );
}
