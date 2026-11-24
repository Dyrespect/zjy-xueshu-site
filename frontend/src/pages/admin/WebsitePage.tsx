import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { ConsentLog, WebsiteSettingsForm } from "@/blocks/website-settings";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { getWebsiteSettings, listConsents, saveWebsiteSettings, type ConsentRow, type WebsiteSettingsData } from "@/lib/website";

/** 后台「官网」：设置（页脚、公安备案号、公开给搜索引擎、维护中）和下单前同意记录。 */
export function WebsitePage() {
  const [data, setData] = useState<WebsiteSettingsData | null>(null);
  const [rows, setRows] = useState<ConsentRow[] | null>(null);
  const load = useCallback(() => {
    getWebsiteSettings().then(setData).catch((e) => toast.error(e instanceof Error ? e.message : "设置没取到"));
    listConsents().then((r) => setRows(r.rows)).catch(() => setRows([]));
  }, []);
  useEffect(load, [load]);
  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold text-foreground">官网</h1>
      <Tabs defaultValue="settings">
        <TabsList>
          <TabsTrigger value="settings">设置</TabsTrigger>
          <TabsTrigger value="consents">下单前同意记录</TabsTrigger>
        </TabsList>
        <TabsContent value="settings" className="pt-4">
          {data ? (
            <WebsiteSettingsForm
              key={JSON.stringify(data.config)}
              data={data}
              onSave={async (config) => {
                setData(await saveWebsiteSettings(config));
                toast.success("官网设置存好了");
              }}
            />
          ) : (
            <p className="text-sm text-muted-foreground">加载中……</p>
          )}
        </TabsContent>
        <TabsContent value="consents" className="pt-4">
          {rows ? <ConsentLog rows={rows} /> : <p className="text-sm text-muted-foreground">加载中……</p>}
        </TabsContent>
      </Tabs>
    </div>
  );
}
