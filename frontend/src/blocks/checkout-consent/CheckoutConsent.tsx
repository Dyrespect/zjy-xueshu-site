import type { ReactNode } from "react";

import type { ConsentKey } from "@/lib/website-types";
import { cn } from "@/lib/utils";

/**
 * 下单页付款按钮上面那一组勾选（三项都勾上才能付款）：
 * 1 同意用户协议和隐私政策；2 单独同意材料交给第三方 AI 处理（含境外，个人信息保护法第三十九条要「单独同意」，所以不和第 1 项捆在一起）；
 * 3 已了解定制服务开始制作后不支持仅退款（文案草稿 03_下单页.md「付款前勾选」）。
 * 协议链接新窗口打开，不丢下单页上已经选好的东西。只吃 props。
 */

export interface CheckoutConsentProps {
  checked: Record<ConsentKey, boolean>;
  onChange: (key: ConsentKey, value: boolean) => void;
  /** 基础价含几轮修改（价目接口给的） */
  revisions: number;
  /** 点了付款但没勾全：没勾的那几项标出来 */
  showMissing?: boolean;
  /** 上面那行小字；默认「付款前请确认（三项都勾上才能付款）」。需求确认卡上用「开工前请确认……」 */
  legend?: string;
  /** 没勾全时的提示；默认「还有没勾的，勾上才能付款。」 */
  missingText?: string;
}

const link = "text-primary underline underline-offset-2 hover:text-primary-hover";

function Doc({ href, children }: { href: string; children: ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={link}>
      {children}
    </a>
  );
}

export function consentItems(revisions: number): { key: ConsentKey; label: ReactNode }[] {
  return [
    {
      key: "terms_privacy",
      label: (
        <>
          我已阅读并同意<Doc href="/terms">《用户协议》</Doc>和<Doc href="/privacy">《隐私政策》</Doc>。
        </>
      ),
    },
    {
      key: "ai_processing",
      label: (
        <>
          我同意把我上传的材料交给第三方 AI 模型处理，只用来做这一单；其中包括境外的服务（美国 Anthropic 公司的 Claude），材料会传到境外。
          详见<Doc href="/privacy#ai">隐私政策「AI 处理和出境」</Doc>。
        </>
      ),
    },
    {
      key: "custom_no_refund",
      label: <>我已了解：这是按我的材料单独做的定制服务，开始制作后不支持仅退款，不满意可以改 {revisions} 轮。</>,
    },
  ];
}

export function CheckoutConsent({ checked, onChange, revisions, showMissing, legend, missingText }: CheckoutConsentProps) {
  const title = legend ?? "付款前请确认（三项都勾上才能付款）";
  return (
    <fieldset className="flex flex-col gap-2.5" aria-label={title.split("（")[0]}>
      <legend className="mb-1 text-xs text-muted-foreground">{title}</legend>
      {consentItems(revisions).map((it) => {
        const miss = showMissing && !checked[it.key];
        return (
          <label key={it.key} className={cn("flex cursor-pointer items-start gap-2.5 text-xs leading-relaxed text-body", miss && "text-foreground")}>
            <input
              type="checkbox"
              name={it.key}
              checked={checked[it.key]}
              onChange={(e) => onChange(it.key, e.target.checked)}
              aria-invalid={miss || undefined}
              className={cn("mt-0.5 size-4 shrink-0 accent-primary", miss && "outline-2 outline-offset-1 outline-destructive")}
            />
            <span>{it.label}</span>
          </label>
        );
      })}
      {showMissing && Object.values(checked).some((v) => !v) ? <p className="text-xs text-destructive">{missingText ?? "还有没勾的，勾上才能付款。"}</p> : null}
    </fieldset>
  );
}
