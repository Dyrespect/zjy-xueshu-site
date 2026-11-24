import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { GatherConfigForm, GatherNumbers, PackPanel, TakedownList, UnlockList } from "@/blocks/admin-gather";
import {
  curate,
  deactivatePack,
  fetchAdminUnlocks,
  fetchGatherConfig,
  fetchGatherOverview,
  fetchGzhReply,
  fetchPacks,
  fetchTakedowns,
  markEvidence,
  pushUnlock,
  releasePack,
  saveGatherConfig,
} from "@/blocks/admin-gather/load";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import type { AdminPack, AdminTakedown, AdminUnlock, GatherConfig, GatherOverview } from "@/lib/site-types";

/** 后台「聚人」（模块 L）：聚人数、领取列表（看截图、标假、手动发）、网盘链接和公众号回复、版权下架、聚人设置。 */
export default function GatherPage() {
  const [overview, setOverview] = useState<GatherOverview | null>(null);
  const [unlocks, setUnlocks] = useState<AdminUnlock[] | null>(null);
  const [packs, setPacks] = useState<{ items: AdminPack[]; waiting: number } | null>(null);
  const [gzh, setGzh] = useState<{ keyword: string; text: string; missing: string } | null>(null);
  const [takedowns, setTakedowns] = useState<{ items: AdminTakedown[]; open: number; overdue: number } | null>(null);
  const [config, setConfig] = useState<GatherConfig | null>(null);

  const load = useCallback(() => {
    fetchGatherOverview(7).then(setOverview).catch(() => undefined);
    fetchAdminUnlocks().then((r) => setUnlocks(r.items)).catch(() => setUnlocks([]));
    fetchPacks().then(setPacks).catch(() => undefined);
    fetchGzhReply().then(setGzh).catch(() => undefined);
    fetchTakedowns().then(setTakedowns).catch(() => undefined);
    fetchGatherConfig().then(setConfig).catch(() => undefined);
  }, []);
  useEffect(load, [load]);

  const fail = (e: unknown) => toast.error(e instanceof Error ? e.message : "没成功");

  return (
    <div className="max-w-5xl px-5 py-5">
      <h1 className="text-2xl font-semibold">聚人</h1>
      <p className="mt-1 text-sm text-muted-foreground">图库网站 → 转发 → 交截图 → 拿网盘链接 → 去下单页或公众号。</p>
      <Tabs defaultValue={takedowns?.open ? "takedowns" : "numbers"} className="mt-6">
        <TabsList>
          <TabsTrigger value="numbers">聚人数</TabsTrigger>
          <TabsTrigger value="unlocks">领取</TabsTrigger>
          <TabsTrigger value="packs">网盘链接{packs?.waiting ? `（${packs.waiting} 人在等）` : ""}</TabsTrigger>
          <TabsTrigger value="takedowns">版权下架{takedowns?.open ? `（${takedowns.open}）` : ""}</TabsTrigger>
          <TabsTrigger value="config">设置</TabsTrigger>
        </TabsList>
        <TabsContent value="numbers" className="pt-4">
          <GatherNumbers data={overview} />
        </TabsContent>
        <TabsContent value="unlocks" className="pt-4">
          <UnlockList
            items={unlocks}
            onMark={async (id, mark) => {
              await markEvidence(id, mark).catch(fail);
              load();
            }}
            onPush={async (id, on) => {
              await pushUnlock(id, on).catch(fail);
              load();
            }}
          />
        </TabsContent>
        <TabsContent value="packs" className="pt-4">
          <PackPanel
            items={packs?.items ?? null}
            waiting={packs?.waiting ?? 0}
            gzhReply={gzh}
            onRelease={async (d) => {
              const r = await releasePack(d);
              toast.success(r.resent ? `上线了，自动补发给 ${r.resent} 个人` : "上线了");
              load();
            }}
            onDeactivate={async (id) => {
              await deactivatePack(id).catch(fail);
              load();
            }}
          />
        </TabsContent>
        <TabsContent value="takedowns" className="pt-4">
          <TakedownList
            items={takedowns?.items ?? null}
            onDecide={async (id, decision, ids) => {
              await curate("takedown", id, decision, ids ? { figure_ids: ids } : {}).then(
                () => toast.success(decision === "hide" ? "下架了：网站和插件马上不再出现" : "记下了"),
                fail,
              );
              load();
            }}
          />
        </TabsContent>
        <TabsContent value="config" className="pt-4">
          <GatherConfigForm
            config={config}
            onSave={async (values) => {
              setConfig(await saveGatherConfig(values));
              toast.success("保存了");
            }}
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}
