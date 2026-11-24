import { Download } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { AdminInvoices, InvoiceMetricsStrip, InvoiceNotices, ManualInvoiceDialog } from "@/blocks/admin-invoices";
import { InvoiceSettingsForm } from "@/blocks/invoice-settings";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  exportInvoicesUrl,
  getInvoiceConfig,
  getInvoiceMetrics,
  getInvoiceSettings,
  issueInvoice,
  listAdminInvoices,
  listInvoiceNotices,
  lookupOrderForInvoice,
  manualInvoice,
  markNoticeSent,
  patchInvoice,
  rejectInvoice,
  runInvoiceSweep,
  saveInvoiceSettings,
  voidInvoice,
  type AdminInvoiceList,
  type AdminInvoiceStatus,
  type InvoiceMetrics,
  type InvoiceNoticeRow,
  type InvoicePublicConfig,
  type InvoiceSettingsData,
} from "@/lib/invoices";

const TABS: { key: AdminInvoiceStatus; label: string; empty: string }[] = [
  { key: "pending", label: "待开票", empty: "没有待开的发票。" },
  { key: "draft", label: "等订单完成", empty: "没有等订单完成的申请。" },
  { key: "issued", label: "已开票", empty: "还没开过发票。" },
  { key: "closed", label: "驳回、作废、撤回", empty: "没有。" },
];

/** 后台「发票」：待开票列表（复制抬头、上传开好的发票、驳回、作废重开）、导出、给平台单录一条、待发通知、设置、评估数据。 */
export function InvoicesPage() {
  const [tab, setTab] = useState<string>("pending");
  const [lists, setLists] = useState<Partial<Record<AdminInvoiceStatus, AdminInvoiceList>>>({});
  const [config, setConfig] = useState<InvoicePublicConfig | null>(null);
  const [metrics, setMetrics] = useState<InvoiceMetrics | null>(null);
  const [notices, setNotices] = useState<InvoiceNoticeRow[] | null>(null);
  const [settings, setSettings] = useState<InvoiceSettingsData | null>(null);
  const [manual, setManual] = useState(false);

  const load = useCallback(() => {
    for (const t of TABS) listAdminInvoices(t.key).then((r) => setLists((s) => ({ ...s, [t.key]: r }))).catch(() => undefined);
    getInvoiceConfig().then(setConfig).catch(() => undefined);
    getInvoiceMetrics(7).then(setMetrics).catch(() => undefined);
    listInvoiceNotices().then((r) => setNotices(r.rows)).catch(() => undefined);
    getInvoiceSettings().then(setSettings).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  const done = (text: string) => {
    toast.success(text);
    load();
    return text;
  };
  const counts = lists.pending?.counts ?? {};
  const listTab = TABS.find((t) => t.key === tab);

  return (
    <div className="max-w-7xl px-5 py-5">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[15px] font-semibold text-foreground">发票</h1>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" onClick={() => setManual(true)} disabled={!config}>
            给平台单录一条
          </Button>
          <Button size="sm" variant="outline" asChild>
            <a href={exportInvoicesUrl(listTab ? listTab.key : "pending")}>
              <Download />
              导出 CSV
            </a>
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => runInvoiceSweep().then(() => done("看过一遍了")).catch(() => toast.error("没跑成"))}
          >
            现在推一遍
          </Button>
        </div>
      </div>
      <p className="mb-5 text-sm text-muted-foreground">
        客人在下单页、付款页、交付页申请；订单到「已完成」才进待开票。开票软件里开好后在这里上传，客人就能下载。
        {settings?.pending_finance.length ? ` 设置里还有 ${settings.pending_finance.length} 项待财务确认。` : ""}
      </p>
      {metrics ? <div className="mb-6"><InvoiceMetricsStrip metrics={metrics} /></div> : null}
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="flex-wrap">
          {TABS.map((t) => (
            <TabsTrigger key={t.key} value={t.key}>
              {t.label}
              {counts[t.key] ? `（${counts[t.key]}）` : ""}
            </TabsTrigger>
          ))}
          <TabsTrigger value="notices">待发通知{notices?.length ? `（${notices.length}）` : ""}</TabsTrigger>
          <TabsTrigger value="settings">设置</TabsTrigger>
        </TabsList>
        {TABS.map((t) => (
          <TabsContent key={t.key} value={t.key} className="pt-4">
            {lists[t.key] && config ? (
              <AdminInvoices
                rows={lists[t.key]!.rows}
                config={config}
                empty={t.empty}
                onIssue={async (row, body) => done(`单号 ${row.order_no} 标记已开（${(await issueInvoice(row.id, body)).amount} 元）`)}
                onReject={async (row, reason) => {
                  await rejectInvoice(row.id, reason);
                  return done(`驳回了单号 ${row.order_no} 的申请`);
                }}
                onVoid={async (row, reason, reopen, fields) => done((await voidInvoice(row.id, reason, reopen, fields)).note || "作废了")}
                onEdit={async (row, fields) => {
                  await patchInvoice(row.id, fields);
                  return done("改好了");
                }}
              />
            ) : (
              <p className="text-sm text-muted-foreground">加载中……</p>
            )}
          </TabsContent>
        ))}
        <TabsContent value="notices" className="pt-4">
          {notices ? (
            <InvoiceNotices
              rows={notices}
              onSent={async (n) => {
                await markNoticeSent(n.id);
                done("记下了");
              }}
            />
          ) : null}
        </TabsContent>
        <TabsContent value="settings" className="pt-4">
          {settings ? (
            <InvoiceSettingsForm
              key={JSON.stringify(settings.config)}
              data={settings}
              onSave={async (c) => {
                setSettings(await saveInvoiceSettings(c));
                getInvoiceConfig().then(setConfig).catch(() => undefined);
              }}
            />
          ) : null}
        </TabsContent>
      </Tabs>
      {config ? (
        <ManualInvoiceDialog
          open={manual}
          onOpenChange={setManual}
          config={config}
          onLookup={lookupOrderForInvoice}
          onSubmit={async (orderId, fields) => done(`录好了（${(await manualInvoice(orderId, fields)).detail || "进待开票"}）`)}
        />
      ) : null}
    </div>
  );
}
