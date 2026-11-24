import { isRouteErrorResponse, Link, useRouteError } from "react-router";

import { StatusView } from "@/blocks/site-shell";
import { SiteFrame } from "@/blocks/site-shell/load";
import { Button } from "@/components/ui/button";
import { usePageMeta } from "@/lib/page-meta";
import { siteTitle } from "@/lib/site-pages";

/**
 * 出错页（React Router 的 errorElement，挂在 App.tsx 最外层）：页面代码出错、懒加载的包下不来（刚上线新版本时常见）都到这里。
 * 404 另有 NotFound；后端整个挂了时 nginx 给静态的 /50x.html（frontend/public/，scripts/site_static_pages.py 生成）。
 */
export function ErrorPage() {
  const err = useRouteError();
  const notFound = isRouteErrorResponse(err) && err.status === 404;
  usePageMeta(siteTitle(notFound ? "页面不存在" : "出错了"));
  if (import.meta.env.DEV && err) console.error(err);
  return (
    <SiteFrame gate={false} className="text-base">
      <StatusView
        code={notFound ? "404" : "500"}
        title={notFound ? "页面不存在" : "出错了"}
        text={
          notFound ? (
            "你访问的地址不存在，可能输入有误，或该页面已下线。"
          ) : (
            <>
              <p>页面加载失败，可能是网站刚刚更新。请刷新页面后重试。</p>
              <p className="mt-2">如果仍无法打开，请通过「联系我们」页告知你访问的页面和操作，我们会尽快处理。</p>
            </>
          )
        }
        actions={
          <>
            {!notFound ? <Button onClick={() => window.location.reload()}>刷新</Button> : null}
            <Button variant={notFound ? "default" : "outline"} asChild>
              <Link to="/">回到首页</Link>
            </Button>
            <Button variant="outline" asChild>
              <Link to="/contact">联系我们</Link>
            </Button>
          </>
        }
      />
    </SiteFrame>
  );
}
