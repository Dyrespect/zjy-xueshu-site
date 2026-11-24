/**
 * 后台订单详情里的需求卡：取数、改了发回、代确认都在这里，区块本身只吃 props。
 * ConversationsPage：<OrderBrief orderId={单号} refreshKey={订单卡的版本} onChanged={刷新订单卡} />。
 */
import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { editOrderBrief, getOrderBrief, proxyConfirmBrief, type BriefAdminView } from "@/lib/brief";

import { BriefAdmin } from "./BriefAdmin";

export function OrderBrief({ orderId, refreshKey, onChanged }: { orderId: number; refreshKey?: string; onChanged?: () => void }) {
  const [view, setView] = useState<BriefAdminView | null>(null);
  const load = useCallback(() => getOrderBrief(orderId).then(setView, () => setView(null)), [orderId]);
  useEffect(() => {
    void load();
  }, [load, refreshKey]);
  if (!view) return null;
  const act = async (fn: () => Promise<BriefAdminView>, ok: string) => {
    try {
      setView(await fn());
      toast.success(ok);
      onChanged?.();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "没成");
      throw e;
    }
  };
  return (
    <BriefAdmin
      view={view}
      onSendBack={(answers, note) => act(() => editOrderBrief(orderId, answers, note), "改好了，发给客人确认了")}
      onProxy={(note) => act(() => proxyConfirmBrief(orderId, note), "代客人确认了")}
    />
  );
}
