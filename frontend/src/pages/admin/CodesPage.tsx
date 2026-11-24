import { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";

import { ActivationCodes, type CodeStatusFilter } from "@/blocks/activation-codes";
import { codesExportUrl, generateCodes, listCodes, voidCode, type CodeList } from "@/lib/admin";

export function CodesPage() {
  const [data, setData] = useState<CodeList | null>(null);
  const [status, setStatus] = useState<CodeStatusFilter>("all");
  const [sku, setSku] = useState("");
  const load = useCallback(() => {
    listCodes({ status, sku: sku || undefined })
      .then(setData)
      .catch((e) => toast.error(e instanceof Error ? e.message : "打不开"));
  }, [status, sku]);
  useEffect(load, [load]);
  return (
    <div className="max-w-5xl px-5 py-5">
      <h1 className="mb-6 text-[15px] font-semibold text-foreground">激活码</h1>
      {data ? (
        <ActivationCodes
          data={data}
          status={status}
          onStatus={setStatus}
          sku={sku}
          onSku={setSku}
          onGenerate={async (body) => {
            const r = await generateCodes(body);
            load();
            return r;
          }}
          onVoid={async (row) => {
            try {
              await voidCode(row.id);
              toast.success(`${row.code} 作废了`);
            } catch (e) {
              toast.error(e instanceof Error ? e.message : "没作废成");
            }
            load();
          }}
          exportHref={codesExportUrl}
          conversationHref={(id) => `/admin/conversations/${id}`}
        />
      ) : null}
    </div>
  );
}
