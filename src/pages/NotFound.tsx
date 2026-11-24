import { Link } from "react-router";

import { BlankSlide, StatusView } from "@/blocks/site-shell";
import { SiteFrame } from "@/blocks/site-shell/load";
import { Button } from "@/components/ui/button";
import { usePageMeta } from "@/lib/page-meta";
import { siteTitle } from "@/lib/site-pages";

/** 兜底 404：和官网同一套页头页脚（导航、网站地图都在，走错了能自己找回去）。 */
export default function NotFound() {
  usePageMeta(siteTitle("页面不存在"));
  return (
    <SiteFrame gate={false} className="text-base">
      <StatusView
        code="404"
        title="页面不存在"
        text="你访问的地址不存在，可能输入有误，或该页面已下线。"
        aside={<BlankSlide page="404" />}
        actions={
          <>
            <Button asChild>
              <Link to="/">回到首页</Link>
            </Button>
            <Button variant="outline" asChild>
              <Link to="/sitemap">网站地图</Link>
            </Button>
            {import.meta.env.DEV ? (
              <Link to="/dev/blocks" className="self-center text-sm text-primary hover:text-primary-hover">
                区块陈列（开发用）
              </Link>
            ) : null}
          </>
        }
      />
    </SiteFrame>
  );
}
