import { Download, FileText } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { FinalState } from "@/lib/delivery-types";
import { fileSize } from "@/lib/intake-types";

export interface FinalFilesProps {
  final: FinalState;
}

const KIND_LABEL: Record<string, string> = { PPT: "可编辑 PPT", 讲稿: "逐页讲稿", PDF: "PDF" };

/** 放出后的最终版：PPT（主按钮）、讲稿、PDF。下载每次都由后端重新查订单是否已完成。 */
export function FinalFiles({ final }: FinalFilesProps) {
  if (!final.released && !final.waiting) return null;
  return (
    <section aria-label="最终版" className="mt-8 border-t pt-6">
      <h2 className="text-lg font-semibold text-foreground">可编辑的 PPT 和讲稿</h2>
      {final.waiting ? (
        <p className="mt-2 text-base text-body">马上传上来，传好就放在这里，聊天里也会发给你。</p>
      ) : (
        <>
          <p className="mt-1 text-sm text-body">上台前自己过一遍，按老师的要求微调。AI 辅助制作，请按学校和导师对 AI 使用的要求注明。</p>
          <ul className="mt-4 flex flex-col divide-y rounded-xl border">
            {final.files.map((f) => (
              <li key={f.id} className="flex items-center gap-3 px-4 py-3">
                <FileText className="size-5 shrink-0 text-muted-foreground" />
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm text-foreground">{f.name}</div>
                  <div className="text-xs text-muted-foreground">
                    {KIND_LABEL[f.kind] ?? f.kind} · {fileSize(f.size)}
                  </div>
                </div>
                <Button asChild size="sm" variant={f.kind === "PPT" ? "default" : "outline"}>
                  <a href={f.url} download>
                    <Download />
                    下载
                  </a>
                </Button>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
