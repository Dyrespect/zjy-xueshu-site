import { Loader2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { OutboxItem } from "@/lib/admin-types";
import { msgTime } from "@/lib/intake-types";

export interface PendingReplyProps {
  item: OutboxItem;
  onSend: (text?: string) => Promise<void>;
  onReject: () => Promise<void>;
  /** 现在发不出去的原因（微信客服 48 小时 / 5 条）；有就不让点发送 */
  blockedReason?: string;
  /** 图片的地址（kind=image：付款二维码、负责人微信二维码） */
  imageUrl?: string;
}

const WHO: Record<string, string> = { bot: "助手想发", system: "系统想发", edison: "你写的" };
const IMAGE_NAME: Record<string, string> = { pay_qr: "付款二维码", owner_qr: "负责人微信二维码" };

/**
 * 一条待批（设置里打开了「先给我看」的类别）或发送失败的回复：原文、为什么这么回、发送 / 改一下再发 / 不发。
 * 接单 v2 默认回复直接发，这块只在开了待批、或者发送失败时出现。
 */
export function PendingReply({ item, onSend, onReject, blockedReason, imageUrl }: PendingReplyProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(item.text);
  const [busy, setBusy] = useState<"send" | "reject" | null>(null);
  const failed = item.status === "failed";

  async function run(kind: "send" | "reject", fn: () => Promise<void>) {
    setBusy(kind);
    try {
      await fn();
      setEditing(false);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="rounded-xl border bg-background p-4" aria-label="待批的回复">
      <div className="flex flex-wrap items-baseline gap-x-2 text-sm">
        <span className="font-medium text-foreground">{failed ? "没发出去" : WHO[item.author] ?? "想发"}</span>
        <span className="text-muted-foreground">{item.category}</span>
        <span className="text-xs text-muted-foreground">{msgTime(item.created_at)}</span>
      </div>

      {item.kind === "image" ? (
        imageUrl ? (
          <img src={imageUrl} alt={IMAGE_NAME[item.asset] ?? "图片"} className="mt-3 max-h-40 rounded-lg border" />
        ) : (
          <p className="mt-3 text-sm text-body">{IMAGE_NAME[item.asset] ?? "图片"}</p>
        )
      ) : editing ? (
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          aria-label="改回复"
          className="field-sizing-content mt-3 min-h-20 w-full rounded-lg border border-input bg-background px-3 py-2 text-[15px] leading-relaxed text-foreground outline-none focus-visible:border-ring"
        />
      ) : (
        <p className="mt-3 text-[15px] leading-relaxed whitespace-pre-wrap text-foreground">{item.text}</p>
      )}

      {item.reasons.length ? (
        <div className="mt-3 border-t pt-3">
          <div className="text-xs text-muted-foreground">为什么这么回</div>
          <ul className="mt-1 flex flex-col gap-0.5 text-sm text-body">
            {item.reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
          {item.run ? (
            <div className="mt-1 text-xs text-faint">
              {item.run.model} · 调了 {item.run.requests} 次 · {item.run.input_tokens + item.run.output_tokens} token
            </div>
          ) : null}
        </div>
      ) : null}

      {failed && item.error && !blockedReason ? <p className="mt-3 text-sm text-destructive">{item.error}</p> : null}
      {blockedReason ? <p className="mt-3 text-sm text-destructive">现在发不出去：{blockedReason}</p> : null}

      <div className="mt-4 flex flex-wrap gap-2">
        {editing ? (
          <>
            <Button
              size="sm"
              disabled={!!busy || !draft.trim() || !!blockedReason}
              onClick={() => run("send", () => onSend(draft.trim()))}
            >
              {busy === "send" ? <Loader2 className="animate-spin" /> : null}
              发送改过的
            </Button>
            <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => { setDraft(item.text); setEditing(false); }}>
              算了
            </Button>
          </>
        ) : (
          <>
            <Button size="sm" disabled={!!busy || !!blockedReason} onClick={() => run("send", () => onSend())}>
              {busy === "send" ? <Loader2 className="animate-spin" /> : null}
              {failed ? "再发一次" : "发送"}
            </Button>
            {item.kind === "text" && !item.asset ? (
              <Button size="sm" variant="outline" disabled={!!busy} onClick={() => setEditing(true)}>
                改一下再发
              </Button>
            ) : null}
            <Button size="sm" variant="ghost" disabled={!!busy} onClick={() => run("reject", onReject)}>
              {busy === "reject" ? <Loader2 className="animate-spin" /> : null}
              不发
            </Button>
          </>
        )}
      </div>
    </section>
  );
}
