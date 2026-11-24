import type { DeliveryData } from "@/lib/delivery-types";
import { cnDate } from "@/lib/intake-types";
import { cn } from "@/lib/utils";

export interface DeliveryHeadProps {
  data: DeliveryData;
}

/** 这单现在怎样，一句话。 */
export function statusLine(d: DeliveryData): string {
  if (d.cancelled) return "这单已经作废了。";
  if (d.on_hold) return "这单暂停了（平台上有退款申请），处理完会接着往下走。";
  if (d.final.released) return "可编辑的 PPT 和讲稿在下面，可以下载了。";
  if (d.final.waiting) return "确认收货啦，可编辑的 PPT 和讲稿马上传上来，传好就放在这一页。";
  if (d.revision.open) return "修改意见收到了，改好的一版还在这一页看。";
  if (d.stage === "watermarked") return `第 ${d.latest_round} 版做好了，先看下面的水印版。`;
  if (d.step === 1) return d.due_text || "在做了。";
  if (d.queue_ahead != null) return `资料齐了，${d.queue_ahead ? `前面还有 ${d.queue_ahead} 单，` : ""}预计 ${cnDate(d.eta_date)}前交第一版。`;
  return "还在收资料，齐了就开始排。";
}

/** 交付页的头：品牌字标题、这单的场合和时长、五步进度、现状一句话（psyppt 官网同一套字和间距）。 */
export function DeliveryHead({ data: d }: DeliveryHeadProps) {
  const heading = d.title || `${d.occasion || "汇报"} PPT`;
  const meta = [d.title ? d.occasion : "", d.duration_min ? `${d.duration_min} 分钟` : "", d.present_date ? `${cnDate(d.present_date)}汇报` : ""].filter(Boolean);
  return (
    <section aria-label="这单的进度" className="pt-10 pb-2 sm:pt-14">
      <h1 className="font-display text-3xl leading-tight font-bold tracking-wide text-foreground sm:text-4xl">{heading}</h1>
      {meta.length ? <p className="mt-3 text-base text-body">{meta.join(" · ")}</p> : null}

      <ol className="mt-8 grid grid-cols-5 gap-2 sm:gap-4" aria-label="进度">
        {d.steps.map((s, i) => {
          const done = i < d.step || (d.final.released && i === d.step);
          const current = i === d.step && !d.cancelled && !done;
          return (
            <li key={s} className="flex flex-col gap-2" aria-current={current ? "step" : undefined}>
              <span className={cn("h-0.5 rounded-full", done || current ? "bg-primary" : "bg-border")} />
              <span className="text-xs text-muted-foreground tabular-nums">{String(i + 1).padStart(2, "0")}</span>
              <span className={cn("text-xs leading-snug sm:text-sm", current ? "font-medium text-foreground" : done ? "text-body" : "text-muted-foreground")}>
                {s}
              </span>
            </li>
          );
        })}
      </ol>
      <p className="mt-6 text-base text-foreground">{statusLine(d)}</p>
    </section>
  );
}
