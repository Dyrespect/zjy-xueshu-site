import { useEffect, useState } from "react";

import { OrderBoard } from "@/blocks/order-board";
import { listOrders, type OrderRow } from "@/lib/admin";

export function OrdersPage() {
  const [rows, setRows] = useState<OrderRow[] | null>(null);
  useEffect(() => {
    const load = () => listOrders().then(setRows).catch(() => undefined);
    load();
    const t = window.setInterval(load, 15000);
    return () => window.clearInterval(t);
  }, []);
  return (
    <div className="px-5 py-5">
      <h1 className="mb-4 text-[15px] font-semibold text-foreground">订单</h1>
      {rows ? (
        rows.length ? (
          <OrderBoard rows={rows} hrefFor={(r) => (r.customer_id ? `/admin/conversations/${r.customer_id}` : null)} />
        ) : (
          <p className="text-sm text-muted-foreground">还没有订单</p>
        )
      ) : null}
    </div>
  );
}
