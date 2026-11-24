/**
 * 后台「运维」的接口（/api/admin/ops，要登录）。只通过 api.ts 发请求。
 */
import { api, apiGet, apiPost } from "./api";
import type {
  LifecycleScan,
  OpsAlert,
  OpsBackups,
  OpsConfig,
  OpsErrorRow,
  OpsHealth,
  OpsOverviewData,
  OpsSettingsData,
  ReportPreview,
  SlowRow,
} from "./ops-types";

export * from "./ops-types";

export const getOpsOverview = () => apiGet<OpsOverviewData>("/admin/ops/overview");
export const getOpsHealth = (external = true) => apiGet<OpsHealth>("/admin/ops/health", { external: external ? 1 : 0 });
export const listOpsErrors = (limit = 50) => apiGet<{ rows: OpsErrorRow[] }>("/admin/ops/errors", { limit });
export const listSlowRoutes = (days = 7) => apiGet<{ days: number; rows: SlowRow[] }>("/admin/ops/slow", { days });
export const listOpsAlerts = (status: "open" | "all" = "all") => apiGet<{ rows: OpsAlert[] }>("/admin/ops/alerts", { status });
export const resolveOpsAlert = (id: number) => apiPost<OpsAlert>(`/admin/ops/alerts/${id}/resolve`);
export const getOpsSettings = () => apiGet<OpsSettingsData>("/admin/ops/settings");
export const saveOpsSettings = (config: Partial<OpsConfig>) => api<OpsSettingsData>("/admin/ops/settings", { method: "PUT", json: { config } });
export const testSendOps = () => apiPost<{ ok: boolean; sender: string }>("/admin/ops/test-send");
export const previewReport = (day = "") => apiGet<ReportPreview>("/admin/ops/report/preview", { day: day || undefined });
export const sendReportNow = (day = "") => apiPost<{ ok: boolean; day: string }>("/admin/ops/report/send", { day });
export const getOpsBackups = () => apiGet<OpsBackups>("/admin/ops/backups");
export const runBackupNow = () => apiPost<{ exit: string; detail: string }>("/admin/ops/backups/run");
export const runDrillNow = () => apiPost<{ exit: string; detail: string }>("/admin/ops/backups/drill");
export const getLifecycle = () => apiGet<LifecycleScan>("/admin/ops/lifecycle");
export const flushOpsMetrics = () => apiPost<{ ok: boolean }>("/admin/ops/flush");
