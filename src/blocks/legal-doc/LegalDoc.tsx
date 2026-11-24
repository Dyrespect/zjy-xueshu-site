import type { ReactNode } from "react";
import Markdown, { type Components } from "react-markdown";
import { Link } from "react-router";
import remarkGfm from "remark-gfm";

import { DraftNotice } from "./DraftNotice";

/**
 * 协议类长文（用户协议、隐私政策、免责声明）：标题、版本、草稿提示（待法务或财务确认、还没定的几处）、目录、正文。
 * 正文是 Markdown（pages/site/legal/*.md，律师、Edison 能直接改），用 react-markdown + remark-gfm 渲染（不自己解析）。
 * Markdown 里：
 *   ## 小标题 {#id}      二级标题进目录；{#id} 是锚点（下单页「详见隐私政策 AI 一节」就链到 /privacy#ai）
 *   [字](/privacy#ai)    站内链接走前端路由；https:// 开头的新窗口打开
 *   {company} {phone}…   占位符，渲染前用 vars 换掉（公司名、电话这类来自设置，不写死）
 */

export interface LegalDocData {
  title: string;
  /** 版本（日期）。改了正文要改它：下单页记同意时记的就是这个 */
  version: string;
  /** 一句话：这份讲什么 */
  lead: string;
  /** 这份草稿里还没定的几处（显示在草稿提示里） */
  open: string[];
  /** 底稿是什么（写在页尾，说明这份不是从零写的） */
  basis: string;
  /** 正文（Markdown） */
  markdown: string;
}

export interface LegalDocProps {
  doc: LegalDocData;
  /** 占位符的值：{company} {phone} {phone_note} {email_line} {reply} {revisions} {days} … */
  vars: Record<string, string>;
}

export function fill(text: string, vars: Record<string, string>): string {
  return text.replace(/\{([a-z_]+)\}/g, (m, k: string) => (k in vars ? vars[k] : m));
}

const HEADING = /^##\s+(.+?)\s*\{#([a-z0-9-]+)\}\s*$/gm;

/** 目录：取 Markdown 里带 {#id} 的二级标题 */
export function headings(md: string): { id: string; title: string }[] {
  return [...md.matchAll(HEADING)].map((m) => ({ title: m[1], id: m[2] }));
}

function text(children: ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(text).join("");
  return "";
}

const linkCls = "text-primary underline underline-offset-2 hover:text-primary-hover"; // 正文里的链接带下划线（不能只靠颜色区分，axe link-in-text-block）

const components: Components = {
  h2: ({ children }) => {
    const raw = text(children);
    const m = raw.match(/^(.*?)\s*\{#([a-z0-9-]+)\}\s*$/);
    return (
      <h2 id={m?.[2]} className="scroll-mt-6 border-t pt-10 text-xl leading-snug font-semibold text-foreground">
        {m ? m[1] : children}
      </h2>
    );
  },
  h3: ({ children }) => <h3 className="text-base font-semibold text-foreground">{children}</h3>,
  p: ({ children }) => <p className="leading-[1.8]">{children}</p>,
  ul: ({ children }) => <ul className="flex flex-col gap-2 pl-5 [list-style:disc] marker:text-faint">{children}</ul>,
  ol: ({ children }) => <ol className="flex flex-col gap-2 pl-5 [list-style:decimal] marker:text-muted-foreground">{children}</ol>,
  li: ({ children }) => <li className="leading-[1.8]">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  blockquote: ({ children }) => <blockquote className="border-l-2 pl-4 text-sm text-muted-foreground">{children}</blockquote>,
  table: ({ children }) => (
    <div className="-mx-4 overflow-x-auto px-4 sm:mx-0 sm:px-0">
      <table className="w-full min-w-[32rem] border-collapse text-left text-sm">{children}</table>
    </div>
  ),
  th: ({ children }) => <th className="border-b py-2 pr-4 align-bottom text-xs font-medium text-muted-foreground">{children}</th>,
  td: ({ children }) => <td className="border-b py-3 pr-4 align-top leading-relaxed">{children}</td>,
  a: ({ href = "", children }) =>
    href.startsWith("/") ? (
      <Link to={href} className={linkCls}>
        {children}
      </Link>
    ) : href.startsWith("#") ? (
      <a href={href} className={linkCls}>
        {children}
      </a>
    ) : (
      <a href={href} target="_blank" rel="noopener noreferrer" className={linkCls}>
        {children}
      </a>
    ),
};

export function LegalDoc({ doc, vars }: LegalDocProps) {
  const md = fill(doc.markdown, vars);
  const toc = headings(md);
  return (
    <article className="mx-auto max-w-6xl px-4 pt-10 pb-16 sm:px-6 sm:pt-16" data-version={doc.version}>
      <h1 className="font-headline text-headline font-semibold tracking-[-0.01em] text-foreground">{doc.title}</h1>
      <p className="mt-4 max-w-2xl text-lg leading-relaxed text-body">{fill(doc.lead, vars)}</p>
      <p className="mt-3 text-sm text-muted-foreground tabular-nums">版本 {doc.version}（草稿）</p>
      <DraftNotice open={doc.open} />

      {toc.length ? (
        <nav aria-label="目录" className="mt-10 max-w-2xl">
          <h2 className="text-sm text-muted-foreground">目录</h2>
          <ol className="mt-3 grid gap-x-8 gap-y-2 text-sm sm:grid-cols-2">
            {toc.map((s, i) => (
              <li key={s.id} className="flex gap-2">
                <span className="w-6 shrink-0 text-muted-foreground tabular-nums">{String(i + 1).padStart(2, "0")}</span>
                <a href={`#${s.id}`} className="text-body hover:text-foreground">
                  {s.title}
                </a>
              </li>
            ))}
          </ol>
        </nav>
      ) : null}

      <div className="mt-10 flex max-w-2xl min-w-0 flex-col gap-4 text-base text-body">
        <Markdown remarkPlugins={[remarkGfm]} components={components}>
          {md}
        </Markdown>
      </div>
      <p className="mt-12 max-w-2xl border-t pt-6 text-xs leading-relaxed text-muted-foreground">{doc.basis}</p>
    </article>
  );
}
