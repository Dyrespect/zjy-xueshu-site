import { FileText, Mic } from "lucide-react";
import { Fragment } from "react";

import { fileSize } from "@/lib/intake-types";
import { cn } from "@/lib/utils";

export interface ThreadMessage {
  id: string | number;
  /** right = 「我这边」（网页聊天里是客户自己；后台里是我们发出去的） */
  side: "left" | "right";
  /** 发言人小标签（后台里区分「助手」「你」）；不填不显示 */
  who?: string;
  kind: "text" | "file" | "image" | "voice";
  text: string;
  /** 固定内容的样子：terms 交付和注意事项、payment 付款方式、materials 要发的资料（卡片）；owner_qr / pay_qr 二维码（图下带一行说明） */
  card?: string | null;
  file?: { name: string; size: number; url: string } | null;
  imageUrl?: string | null;
  time: string;
}

export interface ChatThreadProps {
  messages: ThreadMessage[];
  /** 没有消息时显示的话 */
  emptyText?: string;
}

const URL_RE = /(https?:\/\/[^\s，。；！？、]+|\/d\/[A-Za-z0-9_-]{20,})/g;

function Linkified({ text }: { text: string }) {
  const parts = text.split(URL_RE);
  return (
    <>
      {parts.map((p, i) => {
        if (i % 2 === 0) return <Fragment key={i}>{p}</Fragment>;
        const sameSite = p.startsWith("/") || (typeof window !== "undefined" && p.startsWith(window.location.origin));
        const isDelivery = /\/d\/[A-Za-z0-9_-]{20,}$/.test(p);
        return (
          <a
            key={i}
            href={p}
            target={sameSite ? undefined : "_blank"}
            rel="noopener noreferrer"
            className="break-all text-primary underline underline-offset-2"
          >
            {isDelivery ? "打开交付页" : p}
          </a>
        );
      })}
    </>
  );
}

const CIRCLED = /([①②③④⑤⑥⑦⑧⑨⑩])/;
const QR_CAPTION: Record<string, string> = { owner_qr: "负责人微信，扫码加我", pay_qr: "付款二维码" };

/** 「交付什么 + 注意事项」：设置里的原文，按段落、①②③、1. 2. 3. 排成好读的样子（字一个不改）。 */
function TermsBody({ text }: { text: string }) {
  const paras = text.split(/\n{2,}/).map((p) => p.trim()).filter(Boolean);
  return (
    <div className="flex flex-col gap-3">
      {paras.map((p, i) => {
        const circled = p.split(CIRCLED);
        if (circled.length >= 5) {
          const lead = circled[0].trim();
          const items: { mark: string; body: string }[] = [];
          for (let j = 1; j < circled.length; j += 2) items.push({ mark: circled[j], body: (circled[j + 1] ?? "").trim().replace(/[；;。]$/, "") });
          return (
            <div key={i}>
              {lead ? <div className="font-medium text-foreground">{lead}</div> : null}
              <ul className="mt-1 flex flex-col gap-1">
                {items.map((it) => (
                  <li key={it.mark} className="flex gap-2">
                    <span className="shrink-0 text-muted-foreground">{it.mark}</span>
                    <span>{it.body}</span>
                  </li>
                ))}
              </ul>
            </div>
          );
        }
        const lines = p.split("\n");
        if (lines.length > 1 && /[：:]$/.test(lines[0])) {
          return (
            <div key={i}>
              <div className="font-medium text-foreground">{lines[0]}</div>
              <ol className="mt-1 flex flex-col gap-1">
                {lines.slice(1).map((l, j) => {
                  const m = l.match(/^(\d+)[.、．]\s*(.*)$/) ?? l.match(/^(·)\s*(.*)$/);
                  return (
                    <li key={j} className="flex gap-2">
                      <span className="w-4 shrink-0 text-muted-foreground tabular-nums">{m ? m[1] : ""}</span>
                      <span>{m ? m[2] : l}</span>
                    </li>
                  );
                })}
              </ol>
            </div>
          );
        }
        return (
          <p key={i} className={i === 0 ? "font-medium text-foreground" : ""}>
            {p}
          </p>
        );
      })}
    </div>
  );
}

const CARD_TITLE: Record<string, string> = { terms: "交付什么 + 注意事项", payment: "付款方式", materials: "要发的资料" };

function Card({ m }: { m: ThreadMessage }) {
  const title = CARD_TITLE[m.card ?? ""] ?? "";
  return (
    <div className="w-[min(100%,26rem)] rounded-2xl rounded-bl-md border bg-background px-4 py-3.5 text-[14px] leading-relaxed whitespace-normal text-body">
      <div className="mb-2 text-xs text-muted-foreground">{title}</div>
      {m.card === "terms" || m.card === "materials" ? <TermsBody text={m.text} /> : <p className="whitespace-pre-wrap"><Linkified text={m.text} /></p>}
    </div>
  );
}

/** 对话气泡列表。网页聊天和后台会话页共用；数据由页面换成 ThreadMessage 传进来。 */
export function ChatThread({ messages, emptyText }: ChatThreadProps) {
  if (!messages.length) {
    return emptyText ? <p className="py-10 text-center text-sm text-muted-foreground">{emptyText}</p> : null;
  }
  return (
    <ol className="flex flex-col gap-3">
      {messages.map((m, i) => {
        const prev = messages[i - 1];
        const showWho = m.who && (!prev || prev.who !== m.who || prev.side !== m.side);
        const right = m.side === "right";
        const isCard = m.kind === "text" && !!m.card && m.card in CARD_TITLE;
        const bubble = (m.kind === "text" || m.kind === "voice") && !isCard;
        return (
          <li key={m.id} className={cn("flex flex-col", right ? "items-end" : "items-start")}>
            {showWho ? (
              <span className="mb-1 px-1 text-xs text-muted-foreground">
                {m.who} · {m.time}
              </span>
            ) : null}
            <div
              className={cn(
                "max-w-[85%] text-[15px] leading-relaxed break-words whitespace-pre-wrap sm:max-w-[75%]",
                bubble ? "rounded-2xl px-3.5 py-2" : "",
                bubble
                  ? right
                    ? "rounded-br-md bg-highlight text-foreground"
                    : "rounded-bl-md border bg-card text-body"
                  : "",
              )}
            >
              {isCard ? <Card m={m} /> : null}
              {m.kind === "text" && !isCard ? <Linkified text={m.text} /> : null}
              {m.kind === "voice" ? (
                <span className="inline-flex items-center gap-1.5 text-muted-foreground">
                  <Mic className="size-4" />
                  语音
                </span>
              ) : null}
              {m.kind === "file" && m.file ? (
                <a
                  href={m.file.url}
                  className="flex w-64 max-w-full items-center gap-3 rounded-xl border bg-background px-3 py-2.5 hover:bg-accent"
                >
                  <FileText className="size-5 shrink-0 text-muted-foreground" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm text-foreground">{m.file.name}</span>
                    <span className="block text-xs text-muted-foreground">{fileSize(m.file.size)}</span>
                  </span>
                </a>
              ) : null}
              {m.kind === "image" && m.imageUrl ? (
                <figure className="flex flex-col gap-1.5">
                  <a href={m.imageUrl} target="_blank" rel="noopener noreferrer">
                    <img
                      src={m.imageUrl}
                      alt={m.text || "图片"}
                      className={cn("rounded-xl border object-contain", m.card ? "w-[180px] bg-background p-2" : "max-h-56 max-w-[220px]")}
                    />
                  </a>
                  {m.card && QR_CAPTION[m.card] ? (
                    <figcaption className="px-1 text-xs text-muted-foreground">{QR_CAPTION[m.card]}</figcaption>
                  ) : null}
                </figure>
              ) : null}
            </div>
            {!m.who && (!messages[i + 1] || messages[i + 1].side !== m.side) ? (
              <span className="mt-1 px-1 text-xs text-faint">{m.time}</span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
