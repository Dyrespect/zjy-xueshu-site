import { ChevronLeft } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";
import { toast } from "sonner";

import { ChatComposer } from "@/blocks/chat-composer";
import { ChatThread, type ThreadMessage } from "@/blocks/chat-thread";
import { ConversationList } from "@/blocks/conversation-list";
import { OrderBrief } from "@/blocks/brief-admin/load";
import { OrderCard } from "@/blocks/order-card";
import { PendingReply } from "@/blocks/pending-reply";
import { Button } from "@/components/ui/button";
import {
  CHANNEL_LABEL,
  approveOutbox,
  confirmOrder,
  createManualOrder,
  deliverOrder,
  deliverableFromFactory,
  discardUnpublished,
  getAdminSettings,
  getConversation,
  listConversations,
  listFactoryJobs,
  patchCustomer,
  patchOrder,
  pushOrder,
  rejectOutbox,
  releaseFinal,
  releaseNow,
  resolveNeed,
  sendAsEdison,
  setFilePurpose,
  setOrderRush,
  setTakeover,
  uploadDeliverable,
  voidOrder,
  type AdminMessage,
  type AdminSettings,
  type ConversationDetail,
  type ConversationRow,
  type SendWindow,
} from "@/lib/admin";
import { msgTime } from "@/lib/intake-types";
import { cn } from "@/lib/utils";

/** 没认领的会话：给它手动开一单（先做后付、熟人），不收码 */
function ManualOrder({ skus, onCreate }: { skus: ConversationDetail["base_skus"]; onCreate: (sku: string, why: string) => Promise<void> }) {
  const [sku, setSku] = useState(skus[1]?.sku ?? skus[0]?.sku ?? "");
  const [why, setWhy] = useState("");
  const [busy, setBusy] = useState(false);
  const cls = "h-8 w-full rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";
  return (
    <div className="px-4 py-4 text-sm">
      <h2 className="text-[15px] font-semibold text-foreground">还没有订单</h2>
      <p className="mt-1 text-body">这个会话还没认领激活码：助手只问答，不收资料。熟人、先做后付的，可以在这里手动开一单。</p>
      <div className="mt-3 flex flex-col gap-2">
        <select aria-label="手动开单的货号" className={cn(cls, "pr-7")} value={sku} onChange={(e) => setSku(e.target.value)}>
          {skus.map((x) => (
            <option key={x.sku} value={x.sku}>
              {x.name} · {x.price} 元
            </option>
          ))}
        </select>
        <input aria-label="为什么手动开" className={cls} placeholder="为什么手动开（比如：师妹，先做后付）" value={why} onChange={(e) => setWhy(e.target.value)} />
        <Button
          size="sm"
          variant="outline"
          className="self-start"
          disabled={busy || !sku}
          onClick={() => {
            setBusy(true);
            void onCreate(sku, why).finally(() => setBusy(false));
          }}
        >
          手动开一单
        </Button>
      </div>
    </div>
  );
}

const WHO: Record<string, string> = { bot: "助手", edison: "你", system: "系统" };

function toThread(m: AdminMessage, customerName: string): ThreadMessage {
  const kind = m.kind === "file" || m.kind === "image" || m.kind === "voice" ? m.kind : "text";
  return {
    id: m.id,
    side: m.direction === "in" ? "left" : "right",
    who: m.direction === "in" ? customerName : WHO[m.sender] ?? "机器人",
    kind,
    text: m.text,
    card: m.card,
    file: m.file ? { name: m.file.name, size: m.file.size, url: m.file.url } : null,
    imageUrl: m.image_url ?? (m.file?.is_image ? m.file.url : null),
    time: msgTime(m.created_at),
  };
}

function windowText(w: SendWindow, channel: string): string {
  if (!w.limited) return channel === "web" ? "不限条数" : "";
  if (!w.can_send) return (w.hours_left ?? 0) <= 0 ? "客户超过 48 小时没说话，现在发不了" : "48 小时内 5 条发满了";
  return `还能发 ${w.sends_left} 条 · 还剩 ${w.hours_left} 小时`;
}

function blocked(w: SendWindow): string | undefined {
  if (!w.limited || w.can_send) return undefined;
  return (w.hours_left ?? 0) <= 0 ? "客户最后一次说话已经超过 48 小时，等他再说一句" : "48 小时内已经发满 5 条，等客户再说一句";
}

export function ConversationsPage() {
  const params = useParams();
  const id = params.id ? Number(params.id) : undefined;
  const [rows, setRows] = useState<ConversationRow[] | null>(null);
  const [detail, setDetail] = useState<ConversationDetail | null>(null);
  const [settings, setSettings] = useState<AdminSettings | null>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const lastCount = useRef(0);

  const loadList = useCallback(() => {
    listConversations().then(setRows).catch(() => undefined);
  }, []);
  const loadDetail = useCallback(() => {
    if (!id) return;
    getConversation(id).then(setDetail).catch((e) => toast.error(e instanceof Error ? e.message : "打不开"));
  }, [id]);
  const refresh = useCallback(() => {
    loadList();
    loadDetail();
  }, [loadList, loadDetail]);

  useEffect(() => {
    getAdminSettings().then(setSettings).catch(() => undefined);
  }, []);
  useEffect(() => {
    setDetail(null);
    lastCount.current = 0;
    refresh();
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible") refresh();
    }, 5000);
    return () => window.clearInterval(t);
  }, [refresh]);
  useEffect(() => {
    const n = (detail?.messages.length ?? 0) + (detail?.outbox.length ?? 0);
    if (n !== lastCount.current) {
      lastCount.current = n;
      bottom.current?.scrollIntoView({ block: "end" });
    }
  }, [detail]);

  async function act(fn: () => Promise<unknown>, ok?: string) {
    try {
      const r = await fn();
      if (r && typeof r === "object" && "status" in r && (r as { status: string }).status === "failed") {
        toast.error(`没发出去：${(r as { error?: string }).error ?? ""}`);
      } else if (ok) {
        toast.success(ok);
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "没成功");
    } finally {
      refresh();
    }
  }

  const c = detail?.customer;
  const o = detail?.order;

  return (
    <div className="flex md:h-screen">
      <aside className={cn("w-full shrink-0 overflow-y-auto border-r md:block md:w-72", id ? "hidden" : "block")}>
        <div className="border-b px-4 py-3">
          <h1 className="text-[15px] font-semibold text-foreground">会话</h1>
        </div>
        {rows ? <ConversationList rows={rows} activeId={id} hrefFor={(x) => `/admin/conversations/${x}`} /> : null}
      </aside>

      {id ? (
        <div className="flex min-w-0 flex-1 flex-col xl:flex-row">
          <section className="flex min-w-0 flex-1 flex-col md:h-screen" aria-label="对话">
            {c && detail ? (
              <>
                <header className="flex flex-wrap items-center justify-between gap-3 border-b px-5 py-3">
                  <div className="flex min-w-0 items-center gap-2">
                    <Link to="/admin/conversations" className="md:hidden" aria-label="回到会话列表">
                      <ChevronLeft className="size-5" />
                    </Link>
                    <div className="min-w-0">
                      <div className="flex items-baseline gap-2">
                        <h2 className="truncate text-[15px] font-semibold text-foreground">{c.name}</h2>
                        <button
                          type="button"
                          className="shrink-0 text-xs text-muted-foreground hover:text-foreground"
                          onClick={() => {
                            const n = window.prompt("这个客户叫什么（会用作工厂 inbox 的文件夹名）", c.nickname);
                            if (n !== null) void act(() => patchCustomer(c.id, { nickname: n }));
                          }}
                        >
                          改称呼
                        </button>
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {CHANNEL_LABEL[c.channel]}
                        {c.source ? ` · 从「${c.source}」来` : ""} · {windowText(detail.window, c.channel)}
                      </div>
                    </div>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    aria-pressed={c.takeover}
                    onClick={() =>
                      act(async () => {
                        const r = await setTakeover(c.id, !c.takeover);
                        if (r.note) toast(r.note);
                      })
                    }
                  >
                    {c.takeover ? "交还助手" : "我来接"}
                  </Button>
                </header>

                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
                  {!detail.bot_ready ? <p className="mb-4 text-sm text-destructive">模型没配，助手不会回（看设置页）。</p> : null}
                  {c.takeover ? <p className="mb-4 text-sm text-foreground">你在接这个客户，助手停着。点「交还助手」恢复。</p> : null}
                  <ChatThread messages={detail.messages.map((m) => toThread(m, c.name))} emptyText="还没有消息" />
                  {detail.last_run?.error ? (
                    <p className="mt-4 text-sm text-destructive">助手上一趟没成功：{detail.last_run.error}</p>
                  ) : null}
                  <div className="mt-4 flex flex-col gap-3">
                    {detail.outbox.map((ob) =>
                      ob.status === "approved" ? (
                        <p key={ob.id} className="text-right text-sm text-muted-foreground">
                          正在发：{ob.text}
                        </p>
                      ) : (
                        <PendingReply
                          key={ob.id}
                          item={ob}
                          imageUrl={ob.kind === "image" && ob.asset ? `/api/admin/intake/assets/${ob.asset}` : undefined}
                          blockedReason={blocked(detail.window)}
                          onSend={(text) => act(() => approveOutbox(ob.id, text))}
                          onReject={() => act(() => rejectOutbox(ob.id))}
                        />
                      ),
                    )}
                  </div>
                  <div ref={bottom} />
                </div>

                <div className="border-t px-5 py-3">
                  <ChatComposer
                    placeholder="自己回一句，直接发出去"
                    sendLabel="发送"
                    disabled={!!blocked(detail.window)}
                    onSendText={(text) => act(() => sendAsEdison(c.id, text))}
                  />
                </div>
              </>
            ) : null}
          </section>

          {!o && detail ? (
            <aside className="w-full shrink-0 overflow-y-auto border-t xl:h-screen xl:w-[380px] xl:border-t-0 xl:border-l" aria-label="订单">
              <ManualOrder skus={detail.base_skus} onCreate={(sku, why) => act(() => createManualOrder(detail.customer.id, sku, why), "开好了")} />
            </aside>
          ) : null}
          {o && settings ? (
            <aside className="w-full shrink-0 overflow-y-auto border-t xl:h-screen xl:w-[380px] xl:border-t-0 xl:border-l" aria-label="订单">
              <OrderBrief orderId={o.id} refreshKey={`${o.stage}-${o.flow_step}`} onChanged={refresh} />
              <OrderCard
                order={o}
                occasions={Object.keys(settings.config.occasions)}
                purposes={settings.purposes}
                deliverableKinds={settings.deliverable_kinds}
                onPatch={(p) => act(() => patchOrder(o.id, p), "改好了")}
                onRush={(v) => act(() => setOrderRush(o.id, v))}
                onResolveNeed={(i) => act(() => resolveNeed(o.id, i))}
                onPurpose={(fid, p) => act(() => setFilePurpose(o.id, fid, p))}
                onPush={(on) => act(() => (on === "completed" ? confirmOrder(o.id) : pushOrder(o.id, on)), "推好了")}
                onVoid={(action) => act(() => voidOrder(o.id, action, action === "return" ? "客户撤单" : "平台退款"), "作废了")}
                onUpload={(file, kind) => act(() => uploadDeliverable(o.id, file, kind), "传上来了")}
                onLoadFactoryJobs={listFactoryJobs}
                onPickFactory={(job, name, kind) => act(() => deliverableFromFactory(o.id, job, name, kind), "从工厂拿过来了")}
                onDeliver={() => act(() => deliverOrder(o.id), "水印版发给客户了")}
                onDiscard={() => act(() => discardUnpublished(o.id), "这一版没交的文件作废了")}
                onReleaseFinal={() => act(() => releaseFinal(o.id), "最终版发了")}
                onReleaseNow={() => act(() => releaseNow(o.id), "水印版发给客人了")}
              />
            </aside>
          ) : null}
        </div>
      ) : (
        <div className="hidden flex-1 items-center justify-center md:flex">
          <p className="text-sm text-muted-foreground">{rows?.length ? "选左边一个客户" : ""}</p>
        </div>
      )}
    </div>
  );
}
