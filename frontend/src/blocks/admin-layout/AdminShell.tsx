import type { ReactNode } from "react";
import { Link } from "react-router";

import { cn } from "@/lib/utils";

import type { NavGroup } from "./nav";

export interface AdminShellProps {
  groups: NavGroup[];
  /** 当前地址，用来高亮菜单 */
  activePath: string;
  onLogout?: () => void;
  children?: ReactNode;
}

function isActive(activePath: string, href: string) {
  return activePath === href || activePath.startsWith(href + "/");
}

/** 后台的外框：左边侧栏（手机上变成顶部一行），右边内容。只吃 props，登录检查在 AdminLayout。 */
export function AdminShell({ groups, activePath, onLogout, children }: AdminShellProps) {
  const items = groups.flatMap((g) => g.items);
  return (
    <div className="flex min-h-screen flex-col bg-background md:flex-row">
      <aside className="hidden w-52 shrink-0 flex-col border-r md:flex">
        <div className="px-5 pt-6 pb-4">
          <div className="text-[15px] font-semibold text-foreground">后台</div>
          <div className="text-xs text-muted-foreground">学术汇报平台</div>
        </div>
        <nav className="flex flex-1 flex-col gap-5 px-2.5 pb-4" aria-label="后台菜单">
          {groups.map((g) => (
            <div key={g.title}>
              <div className="px-2.5 pb-1 text-xs text-muted-foreground">{g.title}</div>
              <ul className="flex flex-col gap-0.5">
                {g.items.map((it) => {
                  const active = isActive(activePath, it.href);
                  return (
                    <li key={it.href}>
                      <Link
                        to={it.href}
                        aria-current={active ? "page" : undefined}
                        className={cn(
                          "flex items-center justify-between rounded-md px-2.5 py-1.5 text-sm transition-colors",
                          active ? "bg-accent font-medium text-foreground" : "text-body hover:bg-accent",
                        )}
                      >
                        <span>{it.label}</span>
                        {it.badge ? (
                          <span className="min-w-5 rounded-full bg-primary px-1.5 text-center text-xs leading-5 font-medium text-primary-foreground">
                            {it.badge}
                          </span>
                        ) : null}
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))}
        </nav>
        {onLogout ? (
          <div className="border-t px-2.5 py-3">
            <button
              type="button"
              onClick={onLogout}
              className="w-full rounded-md px-2.5 py-1.5 text-left text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
            >
              退出登录
            </button>
          </div>
        ) : null}
      </aside>

      {/* 手机宽度：顶部一行菜单，横向滑 */}
      <div className="border-b md:hidden">
        <div className="flex items-center justify-between px-4 pt-3">
          <span className="text-[15px] font-semibold text-foreground">后台</span>
          {onLogout ? (
            <button type="button" onClick={onLogout} className="text-sm text-muted-foreground">
              退出
            </button>
          ) : null}
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 py-2" aria-label="后台菜单">
          {items.map((it) => {
            const active = isActive(activePath, it.href);
            return (
              <Link
                key={it.href}
                to={it.href}
                className={cn(
                  "shrink-0 rounded-md px-2.5 py-1 text-sm",
                  active ? "bg-accent font-medium text-foreground" : "text-body",
                )}
              >
                {it.label}
                {it.badge ? <span className="ml-1 text-primary">{it.badge}</span> : null}
              </Link>
            );
          })}
        </nav>
      </div>

      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
