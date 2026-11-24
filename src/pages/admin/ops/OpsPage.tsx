import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { toast } from "sonner";

import { OpsBackups } from "@/blocks/ops-backups";
import { OpsErrors } from "@/blocks/ops-errors";
import { OpsOverview } from "@/blocks/ops-overview";
import { OpsReport } from "@/blocks/ops-report";
import { OpsSettings } from "@/blocks/ops-settings";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  getLifecycle,
  getOpsBackups,
  getOpsHealth,
  getOpsOverview,
  getOpsSettings,
  listOpsAlerts,
  listOpsErrors,
  listSlowRoutes,
  previewReport,
  resolveOpsAlert,
  runBackupNow,
  runDrillNow,
  saveOpsSettings,
  sendReportNow,
  testSendOps,
  type LifecycleScan,
  type OpsAlert,
  type OpsBackups as BackupsData,
  type OpsConfig,
  type OpsErrorRow,
  type OpsHealth,
  type OpsOverviewData,
  type OpsSettingsData,
  type ReportPreview,
  type SlowRow,
} from "@/lib/ops";

const TABS = ["overview", "errors", "backups", "report", "settings"] as const;

function err(e: unknown, fallback: string) {
  toast.error(e instanceof Error ? e.message : fallback);
}

/** 后台「运维」：总览（关键数字、健康检查、漏斗、队列）、错误与告警、备份、飞书汇报、设置。 */
export function OpsPage() {
  const [params, setParams] = useSearchParams();
  const tab = TABS.includes(params.get("tab") as (typeof TABS)[number]) ? (params.get("tab") as string) : "overview";
  const [overview, setOverview] = useState<OpsOverviewData | null>(null);
  const [health, setHealth] = useState<OpsHealth | null>(null);
  const [alerts, setAlerts] = useState<OpsAlert[]>([]);
  const [errors, setErrors] = useState<OpsErrorRow[]>([]);
  const [slow, setSlow] = useState<SlowRow[]>([]);
  const [backups, setBackups] = useState<BackupsData | null>(null);
  const [settings, setSettings] = useState<OpsSettingsData | null>(null);
  const [preview, setPreview] = useState<ReportPreview | null>(null);
  const [lifecycle, setLifecycle] = useState<LifecycleScan | null>(null);
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    getOpsOverview().then(setOverview).catch((e) => err(e, "打不开"));
    getOpsHealth(true).then(setHealth).catch(() => undefined);
    listOpsAlerts("all").then((r) => setAlerts(r.rows)).catch(() => undefined);
    listOpsErrors().then((r) => setErrors(r.rows)).catch(() => undefined);
    listSlowRoutes(7).then((r) => setSlow(r.rows)).catch(() => undefined);
    getOpsBackups().then(setBackups).catch(() => undefined);
    getOpsSettings().then(setSettings).catch(() => undefined);
    previewReport().then(setPreview).catch(() => undefined);
    getLifecycle().then(setLifecycle).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  const openCount = alerts.filter((a) => a.status === "open" && a.level !== "info").length;
  const save = async (config: Partial<OpsConfig>) => {
    try {
      setSettings(await saveOpsSettings(config));
      toast.success("保存了");
    } catch (e) {
      err(e, "没保存上");
    }
  };

  return (
    <div className="max-w-6xl px-5 py-5">
      <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-[15px] font-semibold text-foreground">运维</h1>
        <Button size="sm" variant="outline" onClick={load}>
          <RefreshCw />
          刷新
        </Button>
      </div>
      <p className="mb-5 text-sm text-muted-foreground">网站自己跑得怎么样：请求、出错、慢不慢、队列、磁盘、证书、备份；要你动手的才推飞书，其余每晚一条日报（时间在「飞书汇报」里改）。</p>
      <Tabs value={tab} onValueChange={(v) => setParams(v === "overview" ? {} : { tab: v }, { replace: true })}>
        <TabsList className="flex-wrap">
          <TabsTrigger value="overview">总览</TabsTrigger>
          <TabsTrigger value="errors">错误与告警{openCount ? `（${openCount}）` : ""}</TabsTrigger>
          <TabsTrigger value="backups">备份</TabsTrigger>
          <TabsTrigger value="report">飞书汇报</TabsTrigger>
          <TabsTrigger value="settings">设置</TabsTrigger>
        </TabsList>
        <TabsContent value="overview" className="pt-4">
          {overview ? <OpsOverview data={overview} health={health} onOpenAlerts={() => setParams({ tab: "errors" }, { replace: true })} /> : null}
        </TabsContent>
        <TabsContent value="errors" className="pt-4">
          <OpsErrors
            alerts={alerts}
            errors={errors}
            slow={slow}
            onResolve={(a) =>
              resolveOpsAlert(a.id)
                .then(() => {
                  toast.success("关掉了");
                  load();
                })
                .catch((e) => err(e, "没关上"))
            }
          />
        </TabsContent>
        <TabsContent value="backups" className="pt-4">
          {backups ? (
            <OpsBackups
              data={backups}
              busy={busy}
              onRun={async () => {
                setBusy("run");
                try {
                  const r = await runBackupNow();
                  if (r.exit === "ok") toast.success("备份好了");
                  else toast.error(`没备份成：${r.detail}`);
                } catch (e) {
                  err(e, "没备份成");
                } finally {
                  setBusy("");
                  load();
                }
              }}
              onDrill={async () => {
                setBusy("drill");
                try {
                  const r = await runDrillNow();
                  if (r.exit === "ok") toast.success("恢复演练过了：都对得上");
                  else toast.error(`恢复演练没过：${r.detail || "核对数对不上"}`);
                } catch (e) {
                  err(e, "没演练成");
                } finally {
                  setBusy("");
                  load();
                }
              }}
            />
          ) : null}
        </TabsContent>
        <TabsContent value="report" className="pt-4">
          {settings ? (
            <OpsReport
              key={JSON.stringify(settings.config.report) + JSON.stringify(settings.config.push)}
              settings={settings}
              preview={preview}
              onSave={save}
              onTestSend={() =>
                testSendOps()
                  .then(() => {
                    toast.success("发出去了，去飞书里看看");
                  })
                  .catch((e) => err(e, "没发出去"))
              }
              onSendNow={() =>
                sendReportNow()
                  .then(() => {
                    toast.success("日报发出去了");
                  })
                  .catch((e) => err(e, "没发出去"))
              }
              onRefreshPreview={() => previewReport().then(setPreview).catch((e) => err(e, "生成不了"))}
            />
          ) : null}
        </TabsContent>
        <TabsContent value="settings" className="pt-4">
          {settings ? <OpsSettings key={JSON.stringify(settings.config)} settings={settings} lifecycle={lifecycle} onSave={save} /> : null}
        </TabsContent>
      </Tabs>
    </div>
  );
}
