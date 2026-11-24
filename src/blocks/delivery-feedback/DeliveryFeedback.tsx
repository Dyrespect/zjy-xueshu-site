import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { Satisfaction } from "@/lib/delivery-types";
import type { OkMessage } from "@/lib/intake-types";
import { cn } from "@/lib/utils";

export interface DeliveryFeedbackProps {
  onSubmit: (body: { satisfaction: Satisfaction; comment: string; share_revised: boolean }) => Promise<OkMessage>;
}

/** 汇报日当天及以后：汇报还顺利吗。 */
export function DeliveryFeedback({ onSubmit }: DeliveryFeedbackProps) {
  const [sat, setSat] = useState<Satisfaction | null>(null);
  const [comment, setComment] = useState("");
  const [share, setShare] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  return (
    <section className="mt-10 border-t pt-6" aria-label="反馈">
      <h2 className="text-lg font-semibold text-foreground">汇报还顺利吗</h2>
      {notice ? (
        <p className="mt-3 text-base text-foreground">{notice}</p>
      ) : (
        <div className="mt-4 flex flex-col gap-3">
          <div className="flex gap-2" role="radiogroup" aria-label="满意吗">
            {(["满意", "一般", "不满意"] as const).map((s) => (
              <button
                key={s}
                type="button"
                role="radio"
                aria-checked={sat === s}
                onClick={() => setSat(s)}
                className={cn("h-9 rounded-md border px-4 text-sm", sat === s ? "border-foreground/30 bg-accent font-medium text-foreground" : "bg-background text-body hover:bg-accent")}
              >
                {s}
              </button>
            ))}
          </div>
          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            aria-label="老师和同学怎么说"
            placeholder="老师和同学怎么说"
            className="field-sizing-content min-h-20 w-full rounded-lg border border-input bg-background px-3 py-2 text-base text-foreground outline-none placeholder:text-muted-foreground focus-visible:border-ring"
          />
          <label className="flex items-center gap-2 text-sm text-body">
            <input type="checkbox" className="accent-primary" checked={share} onChange={(e) => setShare(e.target.checked)} />
            愿意把你自己改过的版本发给我们，帮我们做得更好
          </label>
          <Button
            className="self-start"
            variant="outline"
            size="sm"
            disabled={!sat || busy}
            onClick={async () => {
              if (!sat) return;
              setBusy(true);
              try {
                setNotice((await onSubmit({ satisfaction: sat, comment, share_revised: share })).message);
              } catch (e) {
                setNotice(e instanceof Error ? e.message : "没提交成功，再试一次");
              } finally {
                setBusy(false);
              }
            }}
          >
            提交
          </Button>
        </div>
      )}
    </section>
  );
}
