import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { AppLink } from "@/components/app-link";

export interface ChatIntroProps {
  /** 这个聊天的完整地址（客户回来用） */
  returnUrl: string;
  /** 做好了：交付页地址 */
  deliveryPath?: string | null;
  /** 认领了的单：单号、货号、状态（一行小字） */
  order?: { order_no: string; sku_name: string; stage_label: string } | null;
  /** 需求卡（09 需求引导）：没确认时顶上一条「去确认」，确认了一条小字「看一眼」 */
  brief?: { path: string; confirmed: boolean; text: string } | null;
  /** 「我的订单」：bind = 出「留邮箱」按钮；orders = 出「我的订单」链接；不给 = 都不出（没配邮件服务） */
  account?: "bind" | "orders" | null;
  onBindEmail?: () => void;
  /** 一直挂着的一行（「小鱼是 AI 助手，回复由 AI 生成」），不给就用默认那句 */
  notice?: string;
}

/** 网页聊天顶部：标题、「这一页就是你的专属聊天」+ 复制地址；认领了出单号和状态；做好了出一条去交付页。 */
export function ChatIntro({ returnUrl, deliveryPath, order, brief, account, onBindEmail, notice }: ChatIntroProps) {
  const [copied, setCopied] = useState(false);
  return (
    <header className="border-b bg-background">
      <div className="mx-auto flex max-w-2xl items-start justify-between gap-3 px-4 py-3">
        <div className="min-w-0">
          <h1 className="text-[17px] font-semibold text-foreground">汇报 PPT 定制</h1>
          <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">PsyEngine · 回复会出现在这一页，关掉前记下这一页的地址</p>
          {notice ? <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground" data-testid="chat-ai-notice">{notice}</p> : null}
        </div>
        <Button
          variant="outline"
          size="sm"
          className="shrink-0"
          onClick={() => {
            void navigator.clipboard?.writeText(returnUrl);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 2000);
          }}
        >
          {copied ? <Check /> : <Copy />}
          {copied ? "复制好了" : "复制地址"}
        </Button>
      </div>
      {order ? (
        <div className="border-t">
          <div className="mx-auto flex max-w-2xl items-center justify-between gap-3 px-4 py-2 text-xs">
            <span className="min-w-0 truncate text-muted-foreground" data-testid="chat-order">
              订单 {order.order_no} · {order.sku_name} · <span className="text-foreground">{order.stage_label}</span>
            </span>
            {account === "bind" ? (
              <button type="button" onClick={onBindEmail} className="shrink-0 text-primary hover:text-primary-hover">
                留邮箱，以后凭订单号查
              </button>
            ) : account === "orders" ? (
              <AppLink href="/me" className="shrink-0 text-primary hover:text-primary-hover">
                我的订单
              </AppLink>
            ) : null}
          </div>
        </div>
      ) : null}
      {brief && !deliveryPath ? (
        <div className={brief.confirmed ? "border-t" : "border-t bg-card"}>
          <div className="mx-auto flex max-w-2xl items-center justify-between gap-3 px-4 py-2.5">
            <span className={brief.confirmed ? "text-xs text-muted-foreground" : "text-sm text-foreground"} data-testid="chat-brief">
              {brief.text}
            </span>
            {brief.confirmed ? (
              <AppLink href={brief.path} className="shrink-0 text-xs text-primary hover:text-primary-hover">
                看一眼
              </AppLink>
            ) : (
              <Button asChild size="sm">
                <AppLink href={brief.path}>去确认</AppLink>
              </Button>
            )}
          </div>
        </div>
      ) : null}
      {deliveryPath ? (
        <div className="border-t bg-card">
          <div className="mx-auto flex max-w-2xl items-center justify-between gap-3 px-4 py-2.5">
            <span className="text-sm text-foreground">PPT 做好了</span>
            <Button asChild size="sm">
              <AppLink href={deliveryPath}>去下载</AppLink>
            </Button>
          </div>
        </div>
      ) : null}
    </header>
  );
}
