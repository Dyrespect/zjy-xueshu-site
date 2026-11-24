import { Link } from "react-router";

import type { ConversationRow } from "@/lib/admin-types";
import { msgTime } from "@/lib/intake-types";
import { cn } from "@/lib/utils";

export interface ConversationListProps {
  rows: ConversationRow[];
  activeId?: number;
  hrefFor: (id: number) => string;
}

/** 会话列表：有待批回复的排最前（后端排好的），显示状态和最后一句。 */
export function ConversationList({ rows, activeId, hrefFor }: ConversationListProps) {
  if (!rows.length) {
    return <p className="px-4 py-10 text-center text-sm text-muted-foreground">还没有客户来聊</p>;
  }
  return (
    <ul className="flex flex-col">
      {rows.map((r) => {
        const active = r.id === activeId;
        return (
          <li key={r.id}>
            <Link
              to={hrefFor(r.id)}
              aria-current={active ? "page" : undefined}
              className={cn("block border-b px-4 py-3 transition-colors", active ? "bg-accent" : "hover:bg-accent")}
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate text-sm font-medium text-foreground">{r.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground">{msgTime(r.last_at)}</span>
              </div>
              <p className="mt-0.5 truncate text-sm text-muted-foreground">
                {r.last_from === "customer" ? "" : r.last_from === "edison" ? "你：" : "助手："}
                {r.last_text}
              </p>
              <div className="mt-1.5 flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs">
                {r.pending ? <span className="font-medium text-primary">{r.pending} 条待批</span> : null}
                {r.failed ? <span className="font-medium text-destructive">{r.failed} 条没发出去</span> : null}
                {r.needs ? <span className="text-foreground">发了你微信 {r.needs}</span> : null}
                {r.takeover ? <span className="text-foreground">你在接</span> : null}
                <span className="text-muted-foreground">{r.status_label}</span>
                <span className="text-muted-foreground">{r.channel === "wecom" ? "微信" : "网页"}</span>
              </div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
