import { useMemo, useState } from "react";

import type { FlowInfo, NodeCardInfo, NodeCatalog as Catalog, NodeField } from "@/lib/admin-types";
import { cn } from "@/lib/utils";

export interface NodeCatalogProps {
  catalog: Catalog;
}

const EXIT_KIND: Record<string, string> = { ok: "成功", fail: "失败", wait: "等外部信号" };

function List({ label, items }: { label: string; items: string[] }) {
  return (
    <div className="grid grid-cols-[5.5rem_1fr] gap-x-2 text-sm">
      <dt className="text-xs leading-5 text-muted-foreground">{label}</dt>
      <dd className="text-body">{items.join("；")}</dd>
    </div>
  );
}

function Fields({ title, model, fields }: { title: string; model: string; fields: NodeField[] }) {
  return (
    <div className="min-w-0">
      <div className="text-xs text-muted-foreground">
        {title} <span className="font-mono">{model}</span>
      </div>
      {fields.length ? (
        <ul className="mt-1 flex flex-col gap-0.5 text-xs">
          {fields.map((f) => (
            <li key={f.name} className="leading-5">
              <span className="font-mono text-foreground">{f.name}</span>
              <span className="text-muted-foreground">
                {" "}
                {f.type}
                {f.required ? " · 必填" : ""}
              </span>
              {f.description ? <span className="text-body"> — {f.description}</span> : null}
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-1 text-xs text-muted-foreground">没有字段</p>
      )}
    </div>
  );
}

function Card({ n }: { n: NodeCardInfo }) {
  return (
    <article className="rounded-lg border bg-background px-4 py-3.5" aria-label={n.name}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <h3 className="text-[15px] font-semibold text-foreground">
          {n.name} <span className="ml-1 font-mono text-xs font-normal text-muted-foreground">{n.id}</span>
        </h3>
        <span className="text-xs text-muted-foreground">
          归模块 {n.owner} · {n.status}
          {n.runnable ? "" : " · 只有说明卡"}
        </span>
      </div>
      <p className="mt-1.5 text-sm leading-relaxed text-body">{n.description}</p>
      <dl className="mt-3 flex flex-col gap-1.5">
        <List label="技术栈" items={n.tech} />
        <div className="grid grid-cols-[5.5rem_1fr] gap-x-2 text-sm">
          <dt className="text-xs leading-5 text-muted-foreground">出口</dt>
          <dd className="flex flex-wrap gap-x-3 gap-y-0.5 text-body">
            {n.exits.map((e) => (
              <span key={e.key}>
                <span className="font-mono text-foreground">{e.key}</span> {e.label}
                <span className="text-xs text-muted-foreground">（{EXIT_KIND[e.kind] ?? e.kind}）</span>
              </span>
            ))}
          </dd>
        </div>
        <List label="配置" items={n.config} />
        <List label="发出的事件" items={n.emits} />
        <List label="订阅的事件" items={n.listens} />
        <List label="可替换" items={n.replaceable} />
        <List label="失败与重试" items={[n.failure]} />
        {n.flows.length ? <List label="用在流程" items={n.flows} /> : null}
      </dl>
      <div className="mt-3 grid gap-4 border-t pt-3 sm:grid-cols-2">
        <Fields title="输入" model={n.input.model} fields={n.input.fields} />
        <Fields title="输出" model={n.output.model} fields={n.output.fields} />
      </div>
    </article>
  );
}

function FlowView({ f }: { f: FlowInfo }) {
  return (
    <article className="rounded-lg border bg-background px-4 py-3.5" aria-label={f.name}>
      <h3 className="text-[15px] font-semibold text-foreground">
        {f.name} <span className="ml-1 font-mono text-xs font-normal text-muted-foreground">{f.key} · 对象：{f.subject}</span>
      </h3>
      <p className="mt-1.5 text-sm leading-relaxed text-body">{f.description}</p>
      <ol className="mt-3 flex flex-col gap-2">
        {f.steps.map((s) => (
          <li key={s.id} className="grid grid-cols-[6.5rem_1fr] gap-x-3 border-t pt-2 text-sm first:border-t-0 first:pt-0">
            <div>
              <div className="font-medium text-foreground">{s.stage_label}</div>
              <div className="font-mono text-xs text-muted-foreground">{s.id}</div>
            </div>
            <div className="min-w-0">
              <div className="text-body">
                {s.label}
                <span className="ml-1.5 font-mono text-xs text-muted-foreground">
                  {s.enter ? `进来就跑 ${s.enter}` : s.node}
                </span>
              </div>
              {s.terminal ? (
                <div className="text-xs text-muted-foreground">终点</div>
              ) : (
                <ul className="mt-0.5 flex flex-col text-xs text-muted-foreground">
                  {s.edges.map((e, i) => (
                    <li key={i}>
                      <span className="font-mono text-foreground">{e.on}</span> → {e.to}
                      {e.when.length ? "（有条件）" : ""}
                      {e.manual ? " · 后台能手动推" : ""}
                      {e.loop ? " · 循环" : ""}
                      {e.label ? ` · ${e.label}` : ""}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </li>
        ))}
      </ol>
    </article>
  );
}

/** 节点目录：注册表里所有节点的说明卡（按类别），加上流程定义（节点怎么连）。由后端注册表自动生成。 */
export function NodeCatalog({ catalog }: NodeCatalogProps) {
  const [cat, setCat] = useState("");
  const [tab, setTab] = useState<"nodes" | "flows">("nodes");
  const shown = useMemo(() => catalog.nodes.filter((n) => !cat || n.category === cat), [catalog.nodes, cat]);
  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-center gap-2" role="tablist">
        {(
          [
            ["nodes", `节点 ${catalog.nodes.length}`],
            ["flows", `流程 ${catalog.flows.length}`],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            type="button"
            role="tab"
            aria-selected={tab === k}
            onClick={() => setTab(k)}
            className={cn(
              "h-8 rounded-md border px-3 text-sm",
              tab === k ? "border-foreground/30 bg-accent font-medium text-foreground" : "bg-background text-body hover:bg-accent",
            )}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "nodes" ? (
        <>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {["", ...catalog.categories].map((c) => (
              <button
                key={c || "all"}
                type="button"
                onClick={() => setCat(c)}
                className={cn("py-1", cat === c ? "font-medium text-foreground underline underline-offset-4" : "text-body hover:text-foreground")}
              >
                {c || "全部"}
              </button>
            ))}
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {shown.map((n) => (
              <Card key={n.id} n={n} />
            ))}
          </div>
        </>
      ) : (
        <div className="flex flex-col gap-3">
          {catalog.flows.map((f) => (
            <FlowView key={f.key} f={f} />
          ))}
        </div>
      )}
    </div>
  );
}
