import { expect, test, type Browser, type Page } from "@playwright/test";

/**
 * 聚人走查（模块 L，07 设计第十二节验收第 2 条）：
 * /?from=xhs → 统一页头页脚 → 搜「有调节的中介模型」→ 结果最后一行的导流入口 → 详情 → 「要全部图库？」→ 专属链接（含 s=）
 * → 换一个浏览器上下文打开这个链接（转发带来的新访客 +1）→ 回原页交一张截图 → 看到网盘那段话 → 点「直接下单」（带 from=tuku_unlock_done）
 * → 下单页、兑换页同一套页头页脚 → 提需求、投图、插件、版权问题四页 → 后台「聚人」；手机宽度（390）各截一张。
 *
 * 先起服务（后台密码和三块网址用环境变量给，不碰 .env）：
 *   SITE_MAIN_URL=… SITE_APP_URL=… SITE_FIGURES_URL=… ADMIN_PASSWORD=xxx BACKEND_PORT=8741 FRONTEND_PORT=5181 bash scripts/dev.sh
 * 再跑：FRONTEND_PORT=5181 E2E_ADMIN_PASSWORD=xxx SHOTS_DIR=<截图目录> pnpm e2e gather.spec.ts
 * 截图不进 git（默认写到 test-results/shots/）。测试里贴的网盘链接是 example.invalid 的假地址。
 */

const SHOTS = process.env.SHOTS_DIR ?? "test-results/shots";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "";
const FAKE_PACK = "https://pan.example.invalid/s/walkthrough";

test.describe.configure({ mode: "serial" });
test.use({ deviceScaleFactor: 1 });

async function shot(page: Page, browser: string, name: string, fullPage = false) {
  await page.mouse.move(0, 0);
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== "running"));
  await page.screenshot({ path: `${SHOTS}/${browser}_${name}.png`, fullPage });
}

/** 每次一张内容不同的截图（同一张图交两次会被认成重复） */
async function uniquePng(page: Page): Promise<Buffer> {
  const dataUrl = await page.evaluate(() => {
    const c = document.createElement("canvas");
    c.width = 120;
    c.height = 80;
    const g = c.getContext("2d")!;
    g.fillStyle = `hsl(${Math.floor(Math.random() * 360)} 60% 50%)`;
    g.fillRect(0, 0, 120, 80);
    g.fillText(String(Date.now()), 10, 40);
    return c.toDataURL("image/png");
  });
  return Buffer.from(dataUrl.split(",")[1], "base64");
}

async function releasePack(page: Page) {
  const r = await page.request.post("/api/auth/login", { data: { password: PASSWORD } });
  expect(r.ok()).toBeTruthy();
  const p = await page.request.post("/api/admin/gather/packs", {
    data: { version: "2026.11", tier: "full", url: FAKE_PACK, extract_code: "ab12", count: 7349 },
  });
  expect(p.ok()).toBeTruthy();
  await page.request.post("/api/auth/logout");
}

async function visitShare(browser: Browser, shareUrl: string) {
  const ctx = await browser.newContext();
  const other = await ctx.newPage();
  await other.goto(shareUrl);
  await other.waitForLoadState("networkidle");
  await ctx.close();
}

test("聚人：找图 → 要全部图库 → 转发 → 交截图 → 拿链接 → 去下单", async ({ page, browser, browserName, context }) => {
  test.skip(!PASSWORD, "没给 E2E_ADMIN_PASSWORD");
  test.setTimeout(180_000);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => undefined);
  await releasePack(page);

  // 1 首页：统一页头（找图、提需求、投图、要全部图库、做汇报 PPT 看这里）和页脚（公司、备案号、三组链接）
  await page.goto("/tuku?from=xhs"); // 11-18 站点整合：图库首页在 /tuku（/ 是官网首页）
  const header = page.locator("header").first();
  await expect(header.getByRole("link", { name: "做汇报 PPT 看这里" })).toBeVisible();
  const footer = page.locator("footer");
  await expect(footer.getByText("杭州竹涧云科技有限公司")).toBeVisible();
  await expect(footer.getByText(/浙ICP备/)).toBeVisible();
  for (const name of ["价目", "下单", "交付说明", "找图", "提需求", "投图", "兑换激活码", "版权问题"]) {
    await expect(footer.getByRole("link", { name, exact: true })).toBeVisible();
  }
  await page.waitForLoadState("networkidle");
  await shot(page, browserName, "01_首页");

  // 2 搜索：结果最后一行有「看看我们怎么做」「直接下单」
  await page.getByRole("searchbox").first().fill("有调节的中介模型");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: "最像你要画的" })).toBeVisible({ timeout: 30_000 });
  const order = page.getByRole("link", { name: "直接下单" });
  await expect(order).toHaveAttribute("href", /from=tuku_results/);
  await shot(page, browserName, "02_结果页");

  // 3 详情
  await page.locator('a[href^="/figure/"]').first().click();
  await expect(page.getByRole("button", { name: "复制出处" })).toBeVisible({ timeout: 20_000 });

  // 4 要全部图库：专属链接
  await page.getByRole("button", { name: "要全部图库？" }).first().click();
  const dlg = page.getByRole("dialog");
  await expect(dlg.getByRole("heading", { name: "要全部图库？" })).toBeVisible();
  const shareText = (await dlg.getByText(/\?s=[A-Z0-9]{6}/).textContent()) ?? "";
  const shareUrl = shareText.match(/https?:\/\/\S+\?s=[A-Z0-9]{6}/)?.[0] ?? "";
  expect(shareUrl).not.toBe("");
  await expect(dlg.getByText(FAKE_PACK)).toHaveCount(0); // 没核验，不给链接
  await shot(page, browserName, "03_要全部图库");

  // 5 换一个浏览器上下文打开分享链接（新访客 +1）
  await visitShare(browser, shareUrl);

  // 6 交截图 → 拿到网盘那段话
  await dlg.locator('input[type="file"]').setInputFiles({ name: "转发截图.png", mimeType: "image/png", buffer: await uniquePng(page) });
  await dlg.getByRole("button", { name: "交截图，拿链接" }).click();
  await expect(dlg.getByRole("heading", { name: "全部图库的链接" })).toBeVisible({ timeout: 15_000 });
  await expect(dlg.getByText(FAKE_PACK, { exact: false })).toBeVisible();
  await shot(page, browserName, "04_拿到链接");

  // 7 点「直接下单」→ 下单页（带来源）同一套页头页脚
  const go = dlg.getByRole("link", { name: "直接下单" });
  await expect(go).toHaveAttribute("href", /from=tuku_unlock_done/);
  await go.click();
  await expect(page).toHaveURL(/\/order\?from=tuku_unlock_done/);
  await expect(page.locator("footer").getByRole("link", { name: "找图", exact: true })).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("header").getByRole("link", { name: "价目" })).toBeVisible();
  await page.waitForLoadState("networkidle");
  await shot(page, browserName, "05_下单页");

  // 8 兑换页
  await page.goto("/c/PSY-LINKCHECK");
  await expect(page.locator("footer").getByRole("link", { name: "投图", exact: true })).toBeVisible({ timeout: 15_000 });
  await shot(page, browserName, "06_兑换页");

  // 9 提需求、投图、插件、版权问题
  for (const [path, heading, name] of [
    ["/request", "告诉我们你要画什么", "07_提需求"],
    ["/submit", "投一张你觉得画得好的图", "08_投图"],
    ["/plugin", /把图库装进你的 AI：PsyEngine 图库插件/, "09_插件"],
    ["/copyright", "版权问题", "10_版权问题"],
  ] as const) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible({ timeout: 15_000 });
    await shot(page, browserName, name);
  }
  await expect(page.getByText(/48 小时内从网站和下一版图库包里撤下/)).toBeVisible();

  // 10 后台「聚人」：领取列表里有刚才那一次，带来 ≥1 人、已发链接
  await page.goto("/admin/login");
  await page.getByLabel("密码").fill(PASSWORD);
  await page.getByRole("button", { name: "登录" }).click();
  await page.goto("/admin/gather");
  await expect(page.getByRole("heading", { name: "聚人", exact: true })).toBeVisible({ timeout: 15_000 });
  await shot(page, browserName, "11_后台聚人数");
  await page.getByRole("tab", { name: "领取" }).click();
  await expect(page.getByText(/带来 [1-9]\d* 人/).first()).toBeVisible();
  await shot(page, browserName, "12_后台领取");
  await page.getByRole("tab", { name: /网盘链接/ }).click();
  await shot(page, browserName, "13_后台网盘链接");
  await page.getByRole("tab", { name: "设置" }).click();
  await expect(page.getByLabel("核验方式")).toBeVisible();
  await shot(page, browserName, "14_后台设置", true);
});

test("手机宽度（390）：首页、要全部图库、插件页、下单页", async ({ page, browserName }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/tuku");
  await page.waitForLoadState("networkidle");
  const noHScroll = () => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  expect(await noHScroll()).toBeTruthy();
  await shot(page, browserName, "m01_首页");
  await page.getByRole("button", { name: "要全部图库？" }).first().click();
  await expect(page.getByRole("dialog").getByRole("heading")).toBeVisible();
  await page.waitForTimeout(400);
  await shot(page, browserName, "m02_要全部图库");
  await page.keyboard.press("Escape");
  await page.goto("/plugin");
  await page.waitForLoadState("networkidle");
  expect(await noHScroll()).toBeTruthy();
  await shot(page, browserName, "m03_插件", true);
  await page.goto("/order?from=tuku_nav");
  await page.waitForLoadState("networkidle");
  await shot(page, browserName, "m04_下单页", true);
  await page.goto("/tuku");
  await page.waitForLoadState("networkidle");
  await shot(page, browserName, "m05_首页整页", true);
});
