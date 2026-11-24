import { MessageCircle, QrCode, RefreshCw, Smartphone } from "lucide-react";
import { useState, type ReactNode } from "react";

import { PhoneLogin } from "@/blocks/phone-bind";
import { Button } from "@/components/ui/button";
import type { LoginMethod, QrStatus, SmsSent } from "@/lib/account-types";
import { cn } from "@/lib/utils";

export interface QrState {
  /** 二维码图片地址（服务号带参二维码，mp.weixin.qq.com 出的图） */
  image: string;
  status: QrStatus | "loading" | "error";
  message?: string;
  /** 本机走查的假二维码：多一个「模拟扫码」 */
  fake?: boolean;
}

export interface LoginPanelProps {
  /** 这台设备能用的登录方式（后端按 UA 和配置给）；空 = 不出登录框 */
  methods: LoginMethod[];
  title?: string;
  lead?: ReactNode;
  /** 上一次登录没成的原因（微信授权退回来的） */
  error?: string;
  /** 微信里：点了「微信登录」（整页跳去授权） */
  onWx?: () => void;
  /** 电脑扫码：现在这张码的状态；null = 还没开始 */
  qr?: QrState | null;
  onQrStart?: () => void;
  onQrRefresh?: () => void;
  onFakeScan?: () => void;
  onSmsStart?: (phone: string) => Promise<SmsSent>;
  onSmsVerify?: (phone: string, code: string) => Promise<unknown>;
  /** 卡片外框（兑换页里嵌着用时不要边框） */
  bare?: boolean;
}

const TAB_LABEL: Record<LoginMethod, string> = { wx: "微信登录", qr: "微信扫码", sms: "手机号" };
const TAB_ICON: Record<LoginMethod, typeof QrCode> = { wx: MessageCircle, qr: QrCode, sms: Smartphone };

function QrBox({ qr, onStart, onRefresh, onFakeScan }: { qr?: QrState | null; onStart?: () => void; onRefresh?: () => void; onFakeScan?: () => void }) {
  if (!qr) {
    return (
      <Button size="lg" className="h-11" onClick={onStart}>
        出二维码
      </Button>
    );
  }
  const dead = qr.status === "expired" || qr.status === "error" || qr.status === "used";
  return (
    <div className="flex flex-col items-center gap-3" data-testid="login-qr">
      <div className="relative flex size-48 items-center justify-center rounded-lg border bg-background p-2">
        {qr.image && qr.status !== "loading" ? (
          <img src={qr.image} alt="用微信扫这个二维码登录" width={176} height={176} className={cn("size-44", dead && "opacity-15")} />
        ) : (
          <span className="text-xs text-muted-foreground">正在出二维码……</span>
        )}
        {dead ? (
          <button type="button" onClick={onRefresh} className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-sm text-foreground">
            <RefreshCw className="size-5" />
            {qr.status === "error" ? "没出来，点一下重试" : "二维码过期了，点一下换一张"}
          </button>
        ) : null}
      </div>
      <p className="text-center text-sm leading-relaxed text-body">
        {qr.message || "打开手机微信，扫一扫。第一次扫要先关注我们的服务号，关注后自动登录。"}
      </p>
      {qr.fake && qr.status === "pending" ? (
        <Button variant="outline" size="sm" onClick={onFakeScan}>
          模拟手机扫码（本机走查）
        </Button>
      ) : null}
    </div>
  );
}

/** 登录框：按设备给方式（微信里：微信登录；电脑：微信扫码 / 手机号；手机浏览器：手机号）。只吃 props。 */
export function LoginPanel({ methods, title = "登录", lead, error, onWx, qr, onQrStart, onQrRefresh, onFakeScan, onSmsStart,
  onSmsVerify, bare }: LoginPanelProps) {
  const [tab, setTab] = useState<LoginMethod>(methods[0] ?? "sms");
  if (!methods.length) return null;
  const current = methods.includes(tab) ? tab : methods[0];
  return (
    <section className={cn("flex flex-col gap-5", !bare && "rounded-lg border px-5 py-6")} data-testid="login-panel">
      <div className="flex flex-col gap-1.5">
        <h2 className="text-lg font-semibold text-foreground">{title}</h2>
        {lead ? <div className="text-sm leading-relaxed text-body">{lead}</div> : null}
      </div>
      {methods.length > 1 ? (
        <div role="tablist" aria-label="登录方式" className="grid grid-cols-2 gap-1 rounded-md bg-card p-1">
          {methods.map((m) => {
            const Icon = TAB_ICON[m];
            return (
              <button key={m} type="button" role="tab" aria-selected={current === m} onClick={() => setTab(m)}
                className={cn("flex h-9 items-center justify-center gap-1.5 rounded text-sm transition-colors",
                  current === m ? "bg-background font-medium text-foreground shadow-xs" : "text-muted-foreground hover:text-foreground")}>
                <Icon className="size-4" />
                {TAB_LABEL[m]}
              </button>
            );
          })}
        </div>
      ) : null}
      {error ? <p role="alert" className="rounded-md bg-card px-4 py-3 text-sm leading-relaxed text-foreground">{error}</p> : null}
      {current === "wx" ? (
        <div className="flex flex-col gap-2">
          <Button size="lg" className="h-11" onClick={onWx}>
            用微信登录
          </Button>
          <p className="text-xs leading-relaxed text-muted-foreground">只认出你是谁（服务号下的一个标识），不拿昵称、头像。</p>
        </div>
      ) : null}
      {current === "qr" ? <QrBox qr={qr} onStart={onQrStart} onRefresh={onQrRefresh} onFakeScan={onFakeScan} /> : null}
      {current === "sms" && methods.includes("sms") && onSmsStart && onSmsVerify ? (
        <PhoneLogin onStart={onSmsStart} onVerify={onSmsVerify} idPrefix="login" />
      ) : null}
    </section>
  );
}
