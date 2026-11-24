import { useCallback, useEffect, useState } from "react";
import { Navigate, useParams } from "react-router";

import { AdminInbox, type InboxFilter } from "@/blocks/admin-inbox";
import { curate, loadInbox, updateInbox } from "@/blocks/admin-inbox/load";
import type { InboxKind, InboxList } from "@/lib/figures-types";

const TITLES: Record<InboxKind, string> = {
  feedback: "标签反馈",
  requests: "需求",
  submissions: "投图",
  site: "网站意见",
};

export default function InboxPage() {
  const { kind = "" } = useParams();
  const valid = kind in TITLES;
  const k = kind as InboxKind;
  const [filter, setFilter] = useState<InboxFilter>("all");
  const [data, setData] = useState<InboxList | null>(null);

  const reload = useCallback(() => {
    if (!valid) return;
    setData(null);
    loadInbox(k, filter).then(setData, () => setData({ kind: k, counts: { new: 0, done: 0 }, items: [] }));
  }, [k, filter, valid]);

  useEffect(reload, [reload]);
  useEffect(() => setFilter("all"), [kind]);

  if (!valid) return <Navigate to="/admin/figures/feedback" replace />;
  return (
    <AdminInbox
      kind={k}
      title={TITLES[k]}
      data={data}
      filter={filter}
      onFilter={setFilter}
      onCurate={
        k === "feedback" || k === "submissions"
          ? async (id, decision) => {
              await curate(k === "feedback" ? "tag_fix" : "submit", id, decision);
            }
          : undefined
      }
      onUpdate={async (id, body) => {
        const item = await updateInbox(k, id, body);
        if (body.status) {
          loadInbox(k, filter).then((d) => setData((prev) => (prev ? { ...prev, counts: d.counts } : d)));
        }
        return item;
      }}
    />
  );
}
