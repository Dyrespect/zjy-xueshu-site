import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

import { SITE_PAGES } from "../src/lib/site-pages";

/**
 * 官网走查（站点整合，docs/任务单/08_官网整合_说明.md 第五节）：页面清单里每一页，桌面 1440 和手机 390 各走一遍：
 *   有标题和描述、页头页脚都在（备案号、电话来自设置）、手机宽度不横向滚动、axe 无障碍检查没有严重问题；
 *   页上每个站内链接点过去不是「页面不存在」，外链是 https、新窗口带 noopener。
 * 外加：404、出错页（拦掉一页的代码包）、nginx 用的两张静态页、下单页不勾确认不让付款。
 *
 * 先起服务（假网关、后台密码用环境变量给，不碰 .env）：
 *   SHOP_FAKE_PAY=true SHOP_METHODS=wechat_native=pay.fake,alipay_page=pay.fake ADMIN_PASSWORD=xxx \
 *     BACKEND_PORT=8741 FRONTEND_PORT=5181 bash scripts/dev.sh
 * 再跑：FRONTEND_PORT=5181 BACKEND_PORT=8741 E2E_ADMIN_PASSWORD=xxx SHOT_DIR=<截图文件夹> pnpm e2e e2e/site.spec.ts
 * 失败信息写三件：错在哪、怎么改、看哪份说明。
 */

const SHOT_DIR = process.env.SHOT_DIR ?? "";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "";
const BACKEND = `http://127.0.0.1:${process.env.BACKEND_PORT ?? "8710"}`;
const DOC = "看 docs/任务单/08_官网整合_说明.md 第五节";
const SIZES = [
  { name: "desktop", width: 1440, height: 900 },
  { name: "mobile", width: 390, height: 844 },
];
// 图库那一组的页是科研绘图聚人模块的，只查它通不通（站内链接那条），不查它的样子
const OWN_PAGES = SITE_PAGES.filter((p) => p.group !== "图库");

test.use({ deviceScaleFactor: 1 });

function msg(where: string, fix: string) {
  return `错在哪：${where}；怎么改：${fix}；${DOC}`;
}

async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  // 懒加载的图（loading="lazy"）不在视口里就不下载，等它没意义（官网 v2 首页、样张页非首屏的图都是懒加载）
  await page.waitForFunction(() => Array.from(document.images).every((i) => i.complete || i.loading === "lazy"), null, { timeout: 15_000 });
}

async function shot(page: Page, browser: string, name: string) {
  if (!SHOT_DIR) return;
  await page.mouse.move(0, 0);
  await page.screenshot({ path: `${SHOT_DIR}/${browser}-${name}.png`, fullPage: true });
}

async function linksOn(page: Page) {
  return page.$$eval("a[href]", (as) =>
    as.map((a) => ({ href: a.getAttribute("href") ?? "", target: a.getAttribute("target") ?? "", rel: a.getAttribute("rel") ?? "", text: (a.textContent ?? "").trim().slice(0, 20) })),
  );
}

for (const size of SIZES) {
  test.describe(`官网各页（${size.name}）`, () => {
    for (const p of OWN_PAGES) {
      test(`${p.title} ${p.path}`, async ({ page, browserName }) => {
        await page.setViewportSize({ width: size.width, height: size.height });
        const errors: string[] = [];
        page.on("pageerror", (e) => errors.push(e.message));
        await page.goto(p.path);
        await expect(page.locator("header nav[aria-label='主导航']"), msg(`${p.path} 没有页头导航`, "这一页要包在 SiteFrame / SiteLayout 里")).toBeVisible();
        await expect(page.getByTestId("site-legal"), msg(`${p.path} 页脚没有主体信息`, "页脚读 /api/website/config；看后端是不是起着")).toContainText("统一社会信用代码");
        await expect(page.getByTestId("site-legal")).toContainText("ICP备");
        await settle(page);

        const title = await page.title();
        expect(title, msg(`${p.path} 的 <title> 没带页名`, "lib/site-pages.ts 里这一页的 title，SiteLayout 用它设标题")).toContain(p.path === "/" ? "心理学汇报 PPT 定制" : p.title);
        const desc = await page.locator('meta[name="description"]').getAttribute("content");
        expect(desc ?? "", msg(`${p.path} 没有描述`, "lib/site-pages.ts 里补 description")).not.toBe("");

        const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
        expect(overflow, msg(`${p.path} 在 ${size.width}px 宽时横向多出 ${overflow}px`, "找出撑宽的元素（长网址、表格、不换行的字），加 min-w-0 / break-all / overflow-x-auto")).toBeLessThanOrEqual(0);

        for (const l of await linksOn(page)) {
          if (/^https?:/.test(l.href)) {
            expect(l.href.startsWith("https://"), msg(`${p.path} 的外链「${l.text}」不是 https：${l.href}`, "改成 https 网址")).toBe(true);
          }
          if (l.target === "_blank") {
            expect(l.rel, msg(`${p.path} 新窗口链接「${l.text}」没带 noopener`, '加 rel="noopener noreferrer"')).toContain("noopener");
          }
          if (l.href.startsWith("tel:")) expect(l.href, msg(`${p.path} 电话链接格式不对：${l.href}`, "tel: 后只写数字")).toMatch(/^tel:\+?[0-9-]{6,20}$/);
        }

        if (size.name === "desktop") {
          const axe = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa"]).analyze();
          const bad = axe.violations.filter((v) => v.impact === "critical" || v.impact === "serious");
          expect(
            bad.map((v) => `${v.id}（${v.nodes.length} 处：${v.nodes[0]?.target.join(" ")}）`),
            msg(`${p.path} 无障碍检查有严重问题`, "按 axe 规则名查 https://dequeuniversity.com/rules/axe/ 改；颜色对比不够就在 tokens.css 调"),
          ).toEqual([]);
        }
        expect(errors, msg(`${p.path} 页面脚本报错`, "打开浏览器控制台看报错的那一行")).toEqual([]);
        await shot(page, browserName, `${size.name}-${p.path === "/" ? "home" : p.path.slice(1)}`);
      });
    }
  });
}

test("站内链接都通：页头、页脚和各页正文里的每个站内链接点过去都不是「页面不存在」", async ({ page }) => {
  test.setTimeout(180_000);
  const seen = new Set<string>();
  const from = new Map<string, string>();
  for (const p of OWN_PAGES) {
    await page.goto(p.path);
    await page.waitForLoadState("networkidle");
    for (const l of await linksOn(page)) {
      if (!l.href.startsWith("/") || l.href.startsWith("//") || l.href.startsWith("/site-assets/")) continue;
      const path = l.href.split("#")[0] || "/";
      if (!from.has(path)) from.set(path, `${p.path} 的「${l.text}」`);
      seen.add(path);
    }
  }
  expect(seen.size).toBeGreaterThan(10);
  for (const path of seen) {
    await page.goto(path); // 不等 networkidle：图库页的缩略图多，等不到「网络空闲」；等第一个大标题出来就够判断
    const h1 = (await page.locator("h1").first().textContent({ timeout: 15_000 }).catch(() => "")) ?? "";
    expect(h1, msg(`${from.get(path)} 指向 ${path}，打开是「页面不存在」`, "改链接，或者把那一页挂上路由（lib/site-pages.ts + routes.tsx）")).not.toContain("页面不存在");
  }
});

test("锚点链接停在对应的小节", async ({ page }) => {
  for (const href of ["/privacy#ai", "/privacy#rights", "/disclaimer#ai", "/service#notes", "/help#ai"]) {
    await page.goto(href);
    const id = href.split("#")[1];
    await expect(page.locator(`[id="${id}"]`), msg(`${href} 的锚点 #${id} 不存在`, "协议正文在小标题后写 {#id}，别的页给那一节加 id")).toHaveCount(1);
  }
});

test("没有的地址：同一套页头页脚里的「页面不存在」", async ({ page, browserName }) => {
  await page.goto("/没有这一页");
  await expect(page.getByRole("heading", { name: "页面不存在" })).toBeVisible();
  await expect(page.getByTestId("site-legal")).toContainText("ICP备");
  await expect(page.getByRole("link", { name: "网站地图" }).first()).toBeVisible();
  await shot(page, browserName, "desktop-404");
});

test("出错页：一页的代码包下不来时显示「出错了」，能刷新、能回首页", async ({ page, browserName }) => {
  await page.goto("/");
  await page.route(/PricePage/, (route) => route.abort());
  await page.getByRole("navigation", { name: "主导航" }).getByRole("link", { name: "价目" }).click();
  await expect(page.getByRole("heading", { name: "出错了" }), msg("懒加载失败没有进出错页", "App.tsx 最外层要有 errorElement: <ErrorPage />")).toBeVisible();
  await expect(page.getByRole("button", { name: "刷新" })).toBeVisible();
  await shot(page, browserName, "desktop-500");
});

test("nginx 用的两张静态页：不靠脚本也能看", async ({ page, browserName }) => {
  for (const [file, h] of [["/50x.html", "服务暂时不可用"], ["/maintenance.html", "网站正在维护"]]) {
    await page.goto(file);
    await expect(page.getByRole("heading", { name: h })).toBeVisible();
    await expect(page.getByText("ICP备")).toBeVisible();
    await shot(page, browserName, `static-${file.slice(1, -5)}`);
  }
});

test("robots.txt 跟着「公开给搜索引擎」开关（默认关：全站不让爬）", async ({ request }) => {
  const r = await request.get(`${BACKEND}/robots.txt`);
  expect(r.ok()).toBe(true);
  expect(await r.text(), msg("robots.txt 默认没挡住全站", "看 backend/app/website/router.py 的 robots")).toContain("Disallow: /");
});

test.describe("下单页付款前的确认", () => {
  test("不勾不让付款；勾全了建单、记下同意、到付款页", async ({ page, browserName }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/order");
    await expect(page.getByTestId("order-total").filter({ visible: true })).toBeVisible();
    const pay = page.getByRole("button", { name: "去付款" }).filter({ visible: true }).first();
    test.skip(await pay.isDisabled(), "后端没开付款方式（要 SHOP_FAKE_PAY + SHOP_METHODS），只查得到勾选框");
    await pay.click();
    await expect(page.getByText("还有没勾的，勾上才能付款。").filter({ visible: true })).toBeVisible();
    await expect(page).toHaveURL(/\/order$/);
    await shot(page, browserName, "desktop-order-consent-missing");
    const box = page.locator("[data-consent]").filter({ visible: true });
    for (const name of ["terms_privacy", "ai_processing", "custom_no_refund"]) await box.locator(`input[name="${name}"]`).check();
    await pay.click();
    await expect(page, msg("勾全了还没到付款页", "看 OrderPage 的 pay()：建单后记同意（/api/website/consent）再跳转")).toHaveURL(/\/order\/pay\//);
  });

  test("手机宽度：勾选在底部汇总里，不横向滚动", async ({ page, browserName }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto("/order");
    const box = page.locator("[data-consent]").filter({ visible: true });
    await box.scrollIntoViewIfNeeded();
    await expect(box.locator('input[name="ai_processing"]')).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow).toBeLessThanOrEqual(0);
    await shot(page, browserName, "mobile-order-consent");
  });
});

test.describe("维护中开关", () => {
  test.skip(!PASSWORD, "没给 E2E_ADMIN_PASSWORD");
  test.describe.configure({ mode: "serial" });

  test("打开后官网和下单页显示维护中，关掉恢复", async ({ page, browserName }) => {
    const api = page.request;
    expect((await api.post("/api/auth/login", { data: { password: PASSWORD } })).ok()).toBe(true);
    const cur = await (await api.get("/api/admin/website/settings")).json();
    await api.put("/api/admin/website/settings", { data: { config: { ...cur.config, maintenance: true } } });
    try {
      for (const path of ["/price", "/order"]) {
        await page.goto(path);
        await expect(page.getByRole("heading", { name: "网站正在维护" }), msg(`${path} 开了维护中还能看到内容`, "这一页的外框要用 SiteFrame（gate 默认 true）")).toBeVisible();
      }
      await shot(page, browserName, "desktop-maintenance");
      await page.goto("/admin/website");
      await expect(page.getByRole("heading", { name: "官网" })).toBeVisible();
      await shot(page, browserName, "desktop-admin-website");
    } finally {
      await api.put("/api/admin/website/settings", { data: { config: { ...cur.config, maintenance: false } } });
    }
    await page.goto("/price");
    await expect(page.getByRole("heading", { name: "价目" })).toBeVisible();
  });
});
