import { expect, test, type Page } from "@playwright/test";

/**
 * 图库走查（PRD 第八节第 4 条）：首页 → 点常见要画的 → 结果 → 详情 → 更多类似 → 标签不对提交 → 提需求提交
 * → 要全部图库弹层 → 后台登录看到刚才那两条；手机宽度（390）截首页和结果页。
 *
 * 先起服务（后台密码用环境变量给，不碰 .env）：
 *   ADMIN_PASSWORD=xxx BACKEND_PORT=8720 FRONTEND_PORT=5174 bash scripts/dev.sh
 * 再跑：FRONTEND_PORT=5174 E2E_ADMIN_PASSWORD=xxx pnpm e2e figures.spec.ts
 * 截图写到 docs/截图/图库/<浏览器>_<序号>_<哪一步>.png（SHOTS=0 不截）。
 */

const SHOT_DIR = "../docs/截图/图库";
const PASSWORD = process.env.E2E_ADMIN_PASSWORD ?? "";

test.describe.configure({ mode: "serial" });
test.use({ deviceScaleFactor: 1 }); // 截图用 1 倍，免得 WebKit 的图大三倍

/** 滚一遍让懒加载的图都出来，等图片都加载完 */
async function settle(page: Page) {
  await page.waitForLoadState("networkidle");
  await page.evaluate(async () => {
    const step = window.innerHeight;
    for (let y = 0; y < document.body.scrollHeight; y += step) {
      window.scrollTo(0, y);
      await new Promise((r) => setTimeout(r, 120));
    }
    window.scrollTo(0, 0);
  });
  await page.waitForLoadState("networkidle");
  await page.waitForFunction(() => Array.from(document.images).every((i) => i.complete), null, { timeout: 15_000 });
}

async function shot(page: Page, browser: string, name: string, fullPage = false) {
  if (process.env.SHOTS === "0") return;
  await page.mouse.move(0, 0); // 鼠标挪开，别把悬停的样子截进去
  await page.waitForFunction(() => document.getAnimations().every((a) => a.playState !== "running"));
  await page.screenshot({ path: `${SHOT_DIR}/${browser}_${name}.png`, fullPage });
}

async function noSideScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, "手机宽度不许横向滚动").toBeLessThanOrEqual(0);
}

test("走一遍：找图 → 详情 → 反馈 → 提需求 → 要全部图库 → 后台", async ({ page, browserName }) => {
  test.setTimeout(120_000);
  const contact = `wx: psy_lin_${Date.now() % 10000}`;
  await page.setViewportSize({ width: 1280, height: 900 });

  // 1 首页
  await page.goto("/tuku"); // 11-18 站点整合：图库首页挪到 /tuku（/ 是官网首页）
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("心理学好刊里的图，按你要画的找");
  await expect(page.getByText(/库里共 [\d,]+ 张图，来自 \d+ 本期刊/)).toBeVisible();
  await settle(page);
  await shot(page, browserName, "01_首页", true);

  // 2 点「常见要画的」→ 结果
  await page.getByRole("link", { name: "试次流程", exact: true }).first().click();
  await expect(page).toHaveURL(/\/search\?q=/);
  await expect(page.getByRole("heading", { name: "最像你要画的" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("看起来你要画的是")).toBeVisible();
  await expect(page.getByRole("combobox", { name: "图型" })).toHaveText(/试次流程/);
  await settle(page);
  await shot(page, browserName, "02_结果", true);

  // 3 详情
  const firstCard = page.locator('section[aria-labelledby="group-close"] a').first();
  await firstCard.click();
  await expect(page).toHaveURL(/\/figure\/\d+/);
  await expect(page.getByRole("button", { name: "复制出处" })).toBeVisible();
  await expect(page.getByText("图片版权归原作者和期刊，仅供学习参考").first()).toBeVisible();
  const similar = page.locator('section[aria-labelledby="similar-title"] a');
  await expect(similar).toHaveCount(8, { timeout: 15_000 });
  await settle(page);
  await shot(page, browserName, "03_详情", true);

  // 4 更多类似的
  const firstUrl = page.url();
  await similar.first().click();
  await expect(page).not.toHaveURL(firstUrl);
  const fid = Number(new URL(page.url()).pathname.split("/").pop());
  await expect(page.getByRole("button", { name: "复制出处" })).toBeVisible();
  await settle(page);
  await shot(page, browserName, "04_更多类似的那张", true);

  // 5 标签不对 → 提交
  await page.getByRole("button", { name: "标签不对 / 这张不相关" }).click();
  const fb = page.getByRole("dialog");
  await expect(fb.getByRole("heading", { name: "标签不对？你来改" })).toBeVisible();
  await expect(fb.getByText(/会带上你刚才搜的「试次流程」/)).toBeVisible();
  await fb.getByText("图型不对").click();
  await fb.getByLabel("补充一句（选填）").fill("这张更像实验设计图，不是单个试次的流程");
  await shot(page, browserName, "05_标签不对");
  await fb.getByRole("button", { name: "提交" }).click();
  await expect(page.getByText("收到了，我们会核对这张图的标签。")).toBeVisible();
  await expect(fb).toBeHidden();
  await expect(page.getByText("收到了，我们会核对这张图的标签。")).toBeHidden({ timeout: 10_000 });

  // 6 回到结果页 → 提需求（自动带上刚才搜的话）→ 提交
  await page.goBack();
  await page.goBack();
  await expect(page.getByRole("heading", { name: "没找到想要的？告诉我们你要画什么" })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "提需求" }).click();
  const rq = page.getByRole("dialog");
  await expect(rq.getByLabel("想画什么图")).toHaveValue("试次流程");
  await rq.getByLabel("想画什么图").fill("亲子近红外超扫描的试次流程，要画出两个人同时做任务");
  await rq.getByLabel("研究方向或用了什么方法（选填）").fill("近红外超扫描 fNIRS，亲子互动");
  const sketch = await page.request.get("/api/figures/973/thumb");
  await rq.locator('input[type="file"]').setInputFiles({ name: "我画的草图.webp", mimeType: "image/webp", buffer: await sketch.body() });
  await expect(rq.getByText("我画的草图.webp")).toBeVisible();
  await rq.getByLabel("怎么联系你（选填）").fill(contact);
  await shot(page, browserName, "06_提需求");
  await rq.getByRole("button", { name: "提交" }).click();
  await expect(page.getByText("收到了。找到合适的图会通过你留的联系方式告诉你。")).toBeVisible();
  await expect(rq).toBeHidden();
  await expect(page.getByText("收到了。找到合适的图会通过你留的联系方式告诉你。")).toBeHidden({ timeout: 10_000 });

  // 7 要全部图库
  await page.getByRole("button", { name: "要全部图库？" }).first().click();
  const all = page.getByRole("dialog");
  await expect(all.getByRole("heading", { name: "要全部图库？" })).toBeVisible();
  await expect(all.getByText("复制下面你的专属链接，转发到朋友圈，或者 5 人以上的群")).toBeVisible();
  await expect(all.getByRole("button", { name: "复制专属链接" })).toBeVisible();
  await shot(page, browserName, "07_要全部图库");
  await page.keyboard.press("Escape");

  // 8 后台登录 → 看到刚才那两条
  test.skip(!PASSWORD, "没给 E2E_ADMIN_PASSWORD，后台这一段跳过");
  await page.goto("/admin/figures");
  await expect(page.getByRole("heading", { name: "后台登录" })).toBeVisible();
  await shot(page, browserName, "08_后台登录");
  await page.getByLabel("密码").fill(PASSWORD);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("heading", { name: "标签反馈" })).toBeVisible();
  const row = page.locator("li", { hasText: `#${fid}` }).filter({ hasText: "这张更像实验设计图，不是单个试次的流程" }).first();
  await expect(row).toBeVisible();
  await expect(row).toContainText("图型不对");
  await expect(row).toContainText("试次流程");
  await settle(page);
  await shot(page, browserName, "09_后台_标签反馈");
  await page.getByRole("link", { name: "需求" }).click();
  const req = page.locator("li", { hasText: contact });
  await expect(req).toBeVisible();
  await expect(req).toContainText("亲子近红外超扫描的试次流程");
  await expect(req.locator("img")).toBeVisible();
  await settle(page);
  await shot(page, browserName, "10_后台_需求");
  await page.getByRole("link", { name: "搜索统计" }).click();
  await expect(page.getByRole("heading", { name: "搜索统计" })).toBeVisible();
  await settle(page);
  await shot(page, browserName, "11_后台_搜索统计");
});

test("手机宽度：首页、结果页、详情页不横向滚动", async ({ page, browserName }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/tuku"); // 11-18 站点整合：图库首页挪到 /tuku（/ 是官网首页）
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await settle(page);
  await noSideScroll(page);
  await shot(page, browserName, "12_手机_首页", true);

  await page.getByRole("searchbox").fill("我做的是手机依赖和睡眠的问卷研究，想画假设模型");
  await page.getByRole("button", { name: "找图" }).click();
  await expect(page.getByRole("heading", { name: "最像你要画的" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("combobox", { name: "图型" })).toHaveText(/假设模型与理论框架/);
  await settle(page);
  await noSideScroll(page);
  await shot(page, browserName, "13_手机_结果");

  await page.locator('section[aria-labelledby="group-close"] a').first().click();
  await expect(page.getByRole("button", { name: "复制出处" })).toBeVisible();
  await settle(page);
  await noSideScroll(page);
  await shot(page, browserName, "14_手机_详情");
});

test("库里没有的词：说清楚没有哪个词，给相近的几组和提需求入口", async ({ page, browserName }) => {
  test.setTimeout(90_000);
  await page.setViewportSize({ width: 1280, height: 900 });
  const cases: [string, string][] = [
    ["催眠诱导的流程", "催眠诱导"],
    ["沙盘游戏治疗的流程", "沙盘"],
    ["绘画投射测验 房树人", "房树人"],
  ];
  for (const [i, [q, missing]] of cases.entries()) {
    await page.goto(`/search?q=${encodeURIComponent(q)}`);
    await expect(page.getByText(`库里没有「${missing}」的图，下面是相近的。`)).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("heading", { name: "最像你要画的" })).toBeVisible();
    await expect(page.getByRole("heading", { name: new RegExp(`去掉「${missing}」再找|换成|相邻的图型`) }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "提需求" })).toBeVisible();
    if (i === 0) {
      await settle(page);
      await shot(page, browserName, "15_库里没有的词", true);
      await page.getByRole("button", { name: "提需求" }).click();
      await expect(page.getByRole("dialog").getByLabel("想画什么图")).toHaveValue(q);
    }
  }
});
