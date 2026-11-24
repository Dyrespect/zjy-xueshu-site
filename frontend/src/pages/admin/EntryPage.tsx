import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { EntrySettings } from "@/blocks/entry-settings";
import { getEntryAdmin, makeWecomLink, saveEntryAdmin, type EntryAdmin } from "@/lib/entry";

/** 后台「入口」：微信客服开关和链接、限额、邮件服务状态、资料清单（模块 D）。 */
export function EntryPage() {
  const [data, setData] = useState<EntryAdmin | null>(null);
  const [ver, setVer] = useState(0);
  const load = useCallback(() => {
    getEntryAdmin().then((d) => {
      setData(d);
      setVer((v) => v + 1);
    }, (e) => toast.error(e instanceof Error ? e.message : "读不到"));
  }, []);
  useEffect(load, [load]);
  return (
    <div className="flex flex-col gap-6 px-4 py-6 sm:px-8">
      <div>
        <h1 className="text-xl font-semibold text-foreground">入口</h1>
        <p className="mt-1 text-sm text-muted-foreground">客人拿激活码从哪进来：兑换网页、网页聊天、微信客服。</p>
      </div>
      {data ? (
        <EntrySettings
          key={ver}
          data={data}
          onSave={(body) =>
            saveEntryAdmin(body).then(() => {
              toast.success("存好了");
              load();
            })
          }
          onMakeLink={() =>
            makeWecomLink().then(() => {
              toast.success("生成好了");
              load();
            })
          }
        />
      ) : null}
    </div>
  );
}
