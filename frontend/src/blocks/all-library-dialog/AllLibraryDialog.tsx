import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { SiteLink } from "@/components/site-link";
import { errorText, FormError, ImagePicker } from "@/blocks/figure-forms";
import type { UnlockView } from "@/lib/site-types";

export interface AllLibraryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 这个人这次领取到哪一步了；null = 还在取 */
  view: UnlockView | null;
  /** 取不到时的一句话 */
  error?: string;
  /** 交截图 */
  onUpload: (file: File) => Promise<void>;
  /** 打不开，重发最新版 */
  onResend: () => Promise<void>;
  /** 领到以后的两个入口：看看怎么做（官网）、直接下单（下单页，带 from=tuku_unlock_done） */
  siteUrl: string;
  orderUrl: string;
  onCta?: (target: "site" | "order") => void;
}

const STEPS = ["复制下面你的专属链接，转发到朋友圈，或者 5 人以上的群", "截个图（能看出转发出去了就行）", "在这里交截图，网盘链接马上给你"];

async function copy(text: string, ok: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(ok);
  } catch {
    toast.error("没复制成功，长按或选中文字手动复制");
  }
}

/**
 * 「要全部图库？」（模块 L，gather_figures 流程）：专属链接 → 转发 → 交截图 → 拿网盘链接 → 去下单页或公众号。
 * 「转发换下载」的说法只出现在这个弹层里（check.py 规矩 17）；核验方式是后台设置，这里按 view.verifier 显示对应的一步。
 */
export function AllLibraryDialog({ open, onOpenChange, view, error, onUpload, onResend, siteUrl, orderUrl, onCta }: AllLibraryDialogProps) {
  const [file, setFile] = useState<File | null>(null);
  const [pending, setPending] = useState(false);
  const [formError, setFormError] = useState("");

  async function submit() {
    if (!file) return setFormError("先选一张截图");
    setPending(true);
    setFormError("");
    try {
      await onUpload(file);
      setFile(null);
    } catch (e) {
      setFormError(errorText(e));
    } finally {
      setPending(false);
    }
  }

  async function resend() {
    setPending(true);
    try {
      await onResend();
      toast.success("发了最新的链接");
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setPending(false);
    }
  }

  const sent = view?.stage === "sent";
  const follow = view?.verifier === "follow_gzh";
  const byVisits = view?.verifier === "share_visits";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{sent ? "全部图库的链接" : "要全部图库？"}</DialogTitle>
          <DialogDescription>图片、标签、出处一起打包，定期更新。</DialogDescription>
        </DialogHeader>

        {error ? <p className="text-[15px] text-body">{error}</p> : null}
        {!view && !error ? (
          <div aria-busy="true" className="flex flex-col gap-3">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-9 w-full" />
          </div>
        ) : null}

        {view && sent ? (
          <div className="flex flex-col gap-4">
            <p className="rounded-md border bg-card p-3 text-[15px] leading-relaxed whitespace-pre-line text-foreground">{view.pack_text}</p>
            <div className="flex flex-wrap gap-2">
              <Button onClick={() => copy(view.pack_text, "链接和提取码复制好了")}>复制链接和提取码</Button>
              <Button variant="outline" disabled={pending} onClick={resend}>
                打不开？重发最新版
              </Button>
            </div>
            <div className="border-t pt-4">
              <p className="text-[15px] font-medium text-foreground">要把这些图做进汇报 PPT？</p>
              <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[15px]">
                <SiteLink href={siteUrl} onClick={() => onCta?.("site")} className="text-primary hover:text-primary-hover">
                  看看我们怎么做
                </SiteLink>
                <SiteLink href={orderUrl} onClick={() => onCta?.("order")} className="font-medium text-primary hover:text-primary-hover">
                  直接下单
                </SiteLink>
              </div>
            </div>
          </div>
        ) : null}

        {view && !sent && follow ? (
          <div className="flex flex-col gap-3 text-[15px] leading-relaxed text-body">
            <p>
              在公众号 <span className="font-medium text-foreground">{view.gzh_name}</span> 回复「
              <span className="font-medium text-foreground">{view.gzh_keyword}</span>」，拿全部图库的链接。
            </p>
          </div>
        ) : null}

        {view && !sent && !follow ? (
          <div className="flex flex-col gap-4">
            <ol className="flex flex-col gap-3">
              {(byVisits
                ? ["复制下面你的专属链接，转发到朋友圈，或者 5 人以上的群", `有 ${view.need_visits} 个新朋友点开，网盘链接自动出现在这里`]
                : STEPS
              ).map((s, i) => (
                <li key={s} className="flex gap-3 text-[15px] leading-relaxed text-body">
                  <span className="w-5 shrink-0 font-semibold text-foreground tabular-nums">{i + 1}</span>
                  <span>{s}</span>
                </li>
              ))}
            </ol>
            <div className="flex flex-col gap-2 rounded-md border bg-card p-3">
              <p className="text-sm break-words text-foreground">{view.share_text}</p>
              <Button variant="outline" size="sm" className="self-start" onClick={() => copy(view.share_text, "专属链接复制好了")}>
                复制专属链接
              </Button>
              {view.share_visits > 0 ? (
                <p className="text-xs text-muted-foreground">你的链接已经带来 {view.share_visits} 个新朋友</p>
              ) : null}
            </div>
            {view.reason ? <p className="text-sm text-foreground">{view.reason}</p> : null}
            {view.stage === "passed" ? (
              <p className="text-sm text-muted-foreground">核验过了，链接马上贴上；关掉也不要紧，下次打开这里就有。</p>
            ) : null}
            {!byVisits && view.stage !== "passed" && view.stage !== "checking" ? (
              <div className="flex flex-col gap-3">
                <ImagePicker file={file} onChange={setFile} maxMb={5} onTooLarge={setFormError} buttonText="选截图" />
                <FormError message={formError} />
                <Button disabled={pending || !file} onClick={submit}>
                  {pending ? "交上去…" : "交截图，拿链接"}
                </Button>
              </div>
            ) : null}
          </div>
        ) : null}

        {view && !sent && view.follow_note && !follow ? (
          <p className="border-t pt-3 text-sm text-muted-foreground">{view.follow_note}</p>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
