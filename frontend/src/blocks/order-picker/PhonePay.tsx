import { Check, Copy, ExternalLink } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { copyText } from "@/lib/clipboard";

export interface PhoneFallback {
  /** 后端给的一句（catalog.hint）：「复制这个网址，到微信里打开就能付」/「用电脑打开这个网址扫码付」 */
  hint: string;
  /** 给了就出「复制网址」按钮（微信里能付、手机浏览器还不能付时）；带上选好的档位 */
  copyUrl?: string;
  /** 闲鱼店铺链接（后台「官网」设置）；空 = 不出这个按钮 */
  xianyuUrl?: string;
}

/** 手机上这里还不能直接付时：复制网址到微信里打开付，或者去闲鱼下单。只吃 props。 */
export function PhonePay({ fallback }: { fallback: PhoneFallback }) {
  const [copied, setCopied] = useState<"" | "ok" | "fail">("");
  const copy = async () => {
    if (!fallback.copyUrl) return;
    setCopied((await copyText(fallback.copyUrl)) ? "ok" : "fail");
  };
  return (
    <div className="flex flex-col gap-3 rounded-md border px-4 py-3.5" data-testid="order-phone-pay" data-phone-pay>
      <p className="text-[15px] font-medium leading-relaxed text-foreground">{fallback.hint}</p>
      {fallback.copyUrl ? (
        <>
          <Button size="lg" className="h-11 w-full text-[15px]" onClick={copy}>
            {copied === "ok" ? <Check /> : <Copy />}
            {copied === "ok" ? "复制好了，去微信里粘贴打开" : "复制网址"}
          </Button>
          {copied === "fail" ? (
            <p className="break-all rounded-md bg-muted px-3 py-2 text-xs leading-relaxed text-foreground select-all">
              没复制上，长按下面这行自己复制：{fallback.copyUrl}
            </p>
          ) : (
            <p className="text-xs leading-relaxed text-muted-foreground">
              发到微信里（发给自己或文件传输助手），点开就是这一页，选好的时长档和篇数还在，直接用微信付。
            </p>
          )}
        </>
      ) : null}
      {fallback.xianyuUrl ? (
        <a
          href={fallback.xianyuUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="flex h-10 items-center justify-center gap-1.5 rounded-md border px-3 text-sm font-medium text-foreground hover:bg-accent"
        >
          或者去闲鱼下单
          <ExternalLink className="size-3.5" aria-hidden />
        </a>
      ) : null}
    </div>
  );
}
