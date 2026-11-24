import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { ChannelDue } from "@/blocks/channel-due";
import { ChannelEntry } from "@/blocks/channel-entry";
import { ChannelOrders } from "@/blocks/channel-orders";
import { ChannelSettings } from "@/blocks/channel-settings";
import { ChannelWebOrders } from "@/blocks/channel-web-orders";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  addChannelProduct,
  getChannelDue,
  getChannelOverview,
  getShopStatus,
  listInbox,
  listWebOrders,
  manualEntry,
  markPasted,
  patchChannelProduct,
  refundWebOrder,
  runShopTick,
  saveChannelProfile,
  sendSignal,
  verifyClaim,
  type ChannelOverview,
  type DueItem,
  type InboxRow,
  type ShopStatus,
  type WebOrderRow,
} from "@/lib/shop";

const SIGNAL_DONE: Record<string, string> = {
  completed: "记下了：平台已完成",
  refund_requested: "这一单先暂停了",
  refund_closed: "恢复了",
  refund: "作废了，激活码也作废",
};

function err(e: unknown, fallback: string) {
  toast.error(e instanceof Error ? e.message : fallback);
}

/** 后台「渠道与收款」：该看一眼、人工录单、平台订单、网页订单（退款）、收款设置。 */
export function ChannelsPage() {
  const [tab, setTab] = useState("due");
  const [due, setDue] = useState<DueItem[] | null>(null);
  const [overview, setOverview] = useState<ChannelOverview | null>(null);
  const [inbox, setInbox] = useState<InboxRow[] | null>(null);
  const [web, setWeb] = useState<WebOrderRow[] | null>(null);
  const [status, setStatus] = useState<ShopStatus | null>(null);

  const load = useCallback(() => {
    getChannelDue().then((r) => setDue(r.items)).catch((e) => err(e, "打不开"));
    getChannelOverview().then(setOverview).catch(() => undefined);
    listInbox().then((r) => setInbox(r.rows)).catch(() => undefined);
    listWebOrders().then((r) => setWeb(r.rows)).catch(() => undefined);
    getShopStatus().then(setStatus).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  return (
    <div className="max-w-6xl px-5 py-5">
      <h1 className="mb-1 text-[15px] font-semibold text-foreground">渠道与收款</h1>
      <p className="mb-5 text-sm text-muted-foreground">自有网页的付款和退款、小红书和闲鱼的人工录单都在这里；订单本身在「订单」页。</p>
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="due">该看一眼{due && due.length ? `（${due.length}）` : ""}</TabsTrigger>
          <TabsTrigger value="entry">录单</TabsTrigger>
          <TabsTrigger value="platform">平台订单</TabsTrigger>
          <TabsTrigger value="web">网页订单</TabsTrigger>
          <TabsTrigger value="settings">收款设置</TabsTrigger>
        </TabsList>
        <TabsContent value="due" className="pt-4">
          {due ? (
            <ChannelDue
              items={due}
              onOpen={(it) => setTab(it.inbox_id ? "platform" : "web")}
              onVerify={async (it, ok) => {
                if (!it.inbox_id) return;
                try {
                  const r = await verifyClaim(it.inbox_id, ok);
                  toast.success(ok ? `发码了：${r.code}` : "记下了：没核对上，买家页面会让他再填");
                } catch (e) {
                  err(e, "没核对成");
                }
                load();
              }}
            />
          ) : null}
        </TabsContent>
        <TabsContent value="entry" className="pt-4">
          {overview ? (
            <ChannelEntry
              overview={overview}
              onSubmit={async (body) => {
                const r = await manualEntry(body);
                load();
                return r;
              }}
              onPasted={(id) => markPasted(id).then(load).catch((e) => err(e, "没记上"))}
            />
          ) : null}
        </TabsContent>
        <TabsContent value="platform" className="pt-4">
          {inbox ? (
            <ChannelOrders
              rows={inbox}
              onPasted={(r) => markPasted(r.id).then(load).catch((e) => err(e, "没记上"))}
              onSignal={async (r, kind) => {
                try {
                  await sendSignal(r.platform, r.platform_order_id, kind);
                  toast.success(SIGNAL_DONE[kind]);
                } catch (e) {
                  err(e, "没点成");
                }
                load();
              }}
            />
          ) : null}
        </TabsContent>
        <TabsContent value="web" className="pt-4">
          {web ? (
            <ChannelWebOrders
              rows={web}
              onRefund={async (row, body) => {
                if (!row.order_id) return "这单还没建单，不用退";
                const r = await refundWebOrder({ order_id: row.order_id, ...body });
                load();
                return r.message;
              }}
            />
          ) : null}
        </TabsContent>
        <TabsContent value="settings" className="pt-4">
          {status && overview ? (
            <ChannelSettings
              status={status}
              overview={overview}
              settingsHref="/admin/settings"
              onSaveProfile={async (platform, adapter, enabled) => {
                try {
                  await saveChannelProfile(platform, adapter, enabled);
                  toast.success("改好了");
                } catch (e) {
                  err(e, "没改成");
                }
                load();
              }}
              onAddProduct={async (body) => {
                try {
                  await addChannelProduct(body);
                  toast.success("登记好了");
                } catch (e) {
                  err(e, "没登记上");
                  throw e;
                }
                load();
              }}
              onToggleProduct={(p) => patchChannelProduct(p.id, { active: !p.active }).then(load).catch((e) => err(e, "没改成"))}
              onRunTick={async () => {
                const r = (await runShopTick()) as { confirm?: { completed?: number[] }; sweep?: Record<string, number> };
                load();
                return `跑完了：自动确认 ${r.confirm?.completed?.length ?? 0} 单，关掉过期单 ${r.sweep?.closed ?? 0} 个，补查退款 ${r.sweep?.refunds ?? 0} 笔`;
              }}
            />
          ) : null}
        </TabsContent>
      </Tabs>
    </div>
  );
}
