import { useEffect, useState } from "react";
import { toast } from "sonner";

import { NodeCatalog } from "@/blocks/node-catalog";
import { getNodeCatalog, type NodeCatalog as Catalog } from "@/lib/admin";

/** 后台「节点目录」：注册表里所有节点的说明卡 + 流程定义，由后端自动生成（顶层设计第十八节）。 */
export function NodesPage() {
  const [data, setData] = useState<Catalog | null>(null);
  useEffect(() => {
    getNodeCatalog()
      .then(setData)
      .catch((e) => toast.error(e instanceof Error ? e.message : "打不开"));
  }, []);
  return (
    <div className="max-w-6xl px-5 py-5">
      <h1 className="text-[15px] font-semibold text-foreground">节点目录</h1>
      <p className="mt-1 mb-5 max-w-2xl text-sm text-body">
        每个能力是一个节点，自带说明卡；流程（节点怎么连）是数据，换流程、换节点改配置，不改核心。这一页由注册表自动生成。
      </p>
      {data ? <NodeCatalog catalog={data} /> : null}
    </div>
  );
}
