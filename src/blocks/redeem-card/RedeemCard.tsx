import { ArrowRight, Check, Copy } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { RedeemAction, RedeemView } from "@/lib/entry-types";

export interface RedeemCardProps {
  /** 后端给的状态和按钮；null = 还在查 */
  view: RedeemView | null;
  /** 点了按钮（留在网页做 / 回到聊天 / 用微信客服继续 / 重新输入） */
  onAction?: (a: RedeemAction) => void;
  /** 输入码后点「查看」 */
  onSubmitCode?: (code: string) => void;
  /** 正在认领（按钮转圈、禁用） */
  busy?: boolean;
  error?: string;
  /** 认领前先登录（12 号设计）：没登录时放在「第一步」的登录框（页面传进来，区块不取数） */
  loginSlot?: ReactNode;
  /** 已登录时「换个账号」 */
  onSwitchAccount?: () => void;
}

const COPY: Record<RedeemView["state"], { title: string; lead: string }> = {
  invalid: { title: "用激活码认领订单", lead: "把订单里的激活码填进来，认领以后就能交资料。" },
  not_found: { title: "这个激活码对不上", lead: "核对一下订单发货消息里的码，再填一次。" },
  void: { title: "这枚激活码已经作废了", lead: "订单退款或撤单以后，激活码就不能用了。有疑问可以问一下助手。" },
  expired: { title: "这枚激活码过期了", lead: "有疑问可以问一下助手。" },
  unclaimed: { title: "认领这一单", lead: "认领以后开始收资料。选一个地方继续，两边都是同一个助手。" },
  yours: { title: "这单已经在你这里", lead: "回到原来的聊天接着交资料、看进度。" },
  taken: { title: "这枚激活码已经认领过了", lead: "是你本人的话，回到当时认领的那个网页或微信接着聊。" },
  taken_joinable: { title: "这枚激活码在微信里认领过了", lead: "是你本人的话，可以在网页里接着做，两边的对话算同一单。" },
  addon: { title: "这是加购码", lead: "加购（再改一轮、加急）要挂在一单上用：在那单的聊天里发给助手，或者在这里接到你正在做的那单上。" },
  legacy: { title: "这是旧版档位的码", lead: "去聊天里把码发给助手，助手会转负责人处理。" },
};

const STEPS = ["认领：选网页或微信，把这一单接到你那边。", "交资料：助手按清单一条问完，资料齐了就排期开工。",
  "看水印版：先发一版带水印的，要改的一次说完；满意了确认收货，发可编辑的 PPT 和讲稿。"];

function CopyCode({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="outline"
      size="sm"
      onClick={() =>
        navigator.clipboard?.writeText(code).then(
          () => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1800);
          },
          () => undefined,
        )
      }
    >
      {copied ? <Check /> : <Copy />}
      {copied ? "复制好了" : "复制激活码"}
    </Button>
  );
}

/** 兑换网页的主体：状态标题、激活码、货号、继续的按钮、激活码从哪来。只吃 props。 */
export function RedeemCard({ view, onAction, onSubmitCode, busy, error, loginSlot, onSwitchAccount }: RedeemCardProps) {
  const [input, setInput] = useState("");
  if (!view) {
    return <p className="mx-auto max-w-xl px-4 py-16 text-sm text-muted-foreground sm:px-6">正在查这枚激活码……</p>;
  }
  const needLogin = Boolean(view.login_required && !view.logged_in && loginSlot);
  const loginStep = needLogin && ["unclaimed", "invalid", "not_found", "taken", "taken_joinable", "addon"].includes(view.state);
  const base = COPY[view.state];
  const copy = view.logged_in && view.state === "unclaimed"
    ? { title: base.title, lead: "认领以后，这一单记在你的账号下；接着点选需求、交资料。" }
    : !loginStep ? base
    : view.state === "unclaimed" ? { title: base.title, lead: "第一步登录，第二步认领：登录以后这一单记在你的账号下，换手机、换电脑都能找到，开发票也方便。" }
    : view.state === "taken" || view.state === "taken_joinable" ? { title: base.title, lead: "如果是你认领的，登录同一个账号就能看到进度。" }
    : view.state === "invalid" ? { title: base.title, lead: "第一步登录，第二步填激活码：登录以后，认领的订单都记在你的账号下。" }
    : base;
  const askCode = view.state === "invalid" || view.state === "not_found";
  const actions = view.actions.filter((a) => a.kind !== "retry" && !(loginStep && a.kind === "claim_web"));
  const showSummary = (view.state === "unclaimed" || view.state === "yours") && view.sku_name;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (input.trim()) onSubmitCode?.(input.trim());
  };
  return (
    <div className="mx-auto flex max-w-xl flex-col gap-7 px-4 py-10 sm:px-6">
      <div className="flex flex-col gap-2">
        <h1 className="font-display text-3xl leading-tight font-bold tracking-wide text-foreground">{copy.title}</h1>
        <p className="text-[15px] leading-relaxed text-body">{copy.lead}</p>
      </div>

      {view.code && !askCode ? (
        <div className="flex flex-col items-center gap-3 rounded-lg border px-5 py-6">
          <span className="text-xs text-muted-foreground">激活码</span>
          <span className="font-mono text-2xl font-semibold tracking-wider text-foreground sm:text-[28px]" data-testid="redeem-code">
            {view.code}
          </span>
          <CopyCode code={view.code} />
        </div>
      ) : null}

      {showSummary ? (
        <dl className="grid grid-cols-[5.5rem_1fr] gap-x-4 gap-y-2.5 rounded-lg bg-card px-5 py-4 text-sm">
          <dt className="text-muted-foreground">买的是</dt>
          <dd className="font-medium text-foreground" data-testid="redeem-sku">
            {view.sku_name}
          </dd>
          {view.hours ? (
            <>
              <dt className="text-muted-foreground">时限</dt>
              <dd className="text-body">资料齐了开工，开工后 {view.hours} 小时内先交水印版</dd>
            </>
          ) : null}
          {view.progress ? (
            <>
              <dt className="text-muted-foreground">现在</dt>
              <dd className="text-body">{view.progress}</dd>
            </>
          ) : null}
        </dl>
      ) : null}

      {view.logged_in && view.login_label ? (
        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground" data-testid="redeem-account">
          已登录：{view.login_label}
          {onSwitchAccount ? (
            <button type="button" onClick={onSwitchAccount} className="text-primary underline-offset-2 hover:underline">
              换个账号
            </button>
          ) : null}
        </p>
      ) : null}

      {loginStep ? (
        <div className="flex flex-col gap-3" data-testid="redeem-login-step">
          <span className="text-xs font-medium text-muted-foreground">第一步</span>
          {loginSlot}
        </div>
      ) : null}

      {askCode ? (
        <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
          <label htmlFor="redeem-input" className="sr-only">
            激活码
          </label>
          <Input
            id="redeem-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="PSY-XXXXXXXXX"
            autoComplete="off"
            className="h-11 font-mono text-base tracking-wider uppercase"
          />
          <Button type="submit" size="lg" className="h-11 sm:w-28">
            查看
          </Button>
        </form>
      ) : null}

      {actions.length ? (
        <div className="flex flex-col gap-4">
          {loginStep ? <span className="text-xs font-medium text-muted-foreground">也可以</span> : null}
          {actions
            .map((a) => (
              <div key={a.entry + a.kind} className="flex flex-col gap-1.5">
                <Button
                  size="lg"
                  variant={a.primary ? "default" : "outline"}
                  className="h-11 justify-between text-[15px]"
                  disabled={busy}
                  onClick={() => onAction?.(a)}
                  data-testid={`redeem-action-${a.entry}`}
                >
                  <span>{busy && a.kind === "claim_web" ? "正在认领……" : a.label}</span>
                  <ArrowRight />
                </Button>
                {a.hint ? <p className="text-xs leading-relaxed text-muted-foreground">{a.hint}</p> : null}
              </div>
            ))}
        </div>
      ) : null}

      {error ? (
        <p role="alert" className="rounded-md border border-destructive/40 px-4 py-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}

      {view.state === "unclaimed" ? (
        <ol className="flex flex-col gap-2.5 border-t pt-6">
          {STEPS.map((s, i) => (
            <li key={s} className="flex gap-3 text-sm leading-relaxed text-body">
              <span className="mt-0.5 w-5 shrink-0 text-xs font-medium text-muted-foreground tabular-nums">0{i + 1}</span>
              <span>{s}</span>
            </li>
          ))}
        </ol>
      ) : null}

      <section className="flex flex-col gap-3 border-t pt-6" aria-labelledby="redeem-buy">
        <h2 id="redeem-buy" className="text-sm font-semibold text-foreground">
          激活码从哪来
        </h2>
        <p className="text-sm leading-relaxed text-body">{view.code_hint}</p>
        <ul className="flex flex-col gap-2.5">
          {view.buy.map((b) => (
            <li key={b.label} className="text-sm leading-relaxed text-body">
              <span className="font-medium text-foreground">{b.label}：</span>
              {b.text}
              {b.url ? (
                <a href={b.url} className="ml-1 whitespace-nowrap text-primary hover:text-primary-hover">
                  去看看
                </a>
              ) : null}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
