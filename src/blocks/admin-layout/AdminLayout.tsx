import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Outlet, useLocation, useNavigate } from "react-router";

import { AdminShell } from "./AdminShell";
import { isLoggedIn, loadNavBadges, logout } from "./load";
import { ADMIN_NAV, withBadges } from "./nav";

export interface AdminLayoutProps {
  /** 不传就渲染子路由（<Outlet />）；图库那边的页面也可以直接包一层 <AdminLayout>页面</AdminLayout> */
  children?: ReactNode;
}

/** 后台总框架：没登录跳登录页；侧栏 + 内容。会话上的数每 8 秒刷新一次。 */
export function AdminLayout({ children }: AdminLayoutProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const [ready, setReady] = useState(false);
  const [badges, setBadges] = useState<Record<string, number>>({});

  useEffect(() => {
    let alive = true;
    isLoggedIn().then((ok) => {
      if (!alive) return;
      if (!ok) navigate(`/admin/login?next=${encodeURIComponent(location.pathname + location.search)}`, { replace: true });
      else setReady(true);
    });
    return () => {
      alive = false;
    };
    // 只在进后台时查一次
  }, []);

  const refreshBadges = useCallback(() => {
    loadNavBadges().then(setBadges).catch(() => undefined);
  }, []);

  useEffect(() => {
    if (!ready) return;
    refreshBadges();
    const t = window.setInterval(refreshBadges, 8000);
    return () => window.clearInterval(t);
  }, [ready, refreshBadges, location.pathname]);

  if (!ready) return null;
  return (
    <AdminShell
      groups={withBadges(ADMIN_NAV, badges)}
      activePath={location.pathname}
      onLogout={() => logout().finally(() => navigate("/admin/login", { replace: true }))}
    >
      {children ?? <Outlet />}
    </AdminShell>
  );
}
