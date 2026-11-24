import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

// 交付页走查（模块 E）：逐页看水印版、逐页标修改、核对后提交；平台单去平台确认；确认收货后在同一页下载最终版；手机宽度。
// 要先造好单子（每个浏览器一套）：DELIVERY_TOKENS=<json 路径> SHOT_DIR=<截图文件夹> pnpm e2e e2e/delivery.spec.ts（别只写 delivery：worktree 路径里也有这个词，会把别的走查一起跑了）
//   json 形如 {"chromium": {"revise": 令牌, "platform": 令牌, "confirm": 令牌, "final": 令牌}, "webkit": {...}}
// 没给 DELIVERY_TOKENS 就跳过（这几条会改订单状态，不能对着随便哪个库跑）。
const tokensFile = process.env.DELIVERY_TOKENS;
const shotDir = process.env.SHOT_DIR;
type Tokens = Record<string, { revise: string; platform: string; confirm: string; final: string }>;
const all: Tokens = tokensFile ? JSON.parse(readFileSync(tokensFile, "utf-8")) : {};

async function shot(page: Page, name: string, browser: string, fullPage = true) {
  if (!shotDir) return;
  await page.waitForTimeout(400); // 弹层淡入走完再截
  await page.screenshot({ path: `${shotDir}/${browser}-${name}.png`, fullPage });
}

async function noSideScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

test.describe("交付页", () => {
  test.skip(!tokensFile, "没给 DELIVERY_TOKENS");

  test("逐页看水印版、标修改、核对后提交", async ({ page, browserName }) => {
    const t = all[browserName];
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/d/${t.revise}`);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText("第 1 版做好了，先看下面的水印版。")).toBeVisible();
    const imgs = page.getByRole("img", { name: /水印版/ });
    await expect(imgs).toHaveCount(6);
    await expect(imgs.first()).toHaveJSProperty("complete", true);
    expect(await imgs.first().evaluate((el: HTMLImageElement) => el.naturalWidth)).toBe(1920);
    await shot(page, "1-水印版首屏", browserName, false);

    // 第 2 页、第 5 页要改 + 一条整体意见
    await page.locator("#p-2").getByRole("button", { name: "这页要改" }).click();
    await page.getByLabel("第 2 页要改什么").fill("时间轴太挤，1971—1972 那个点挪到下面一行");
    await page.locator("#p-5").getByRole("button", { name: "这页要改" }).click();
    await page.getByLabel("第 5 页要改什么").fill("图 3 换成原文的 Figure 2");
    await page.getByRole("button", { name: "加一条整体意见" }).click();
    await page.getByLabel("整体意见第 1 条").fill("标题字再大一号");
    const panel = page.getByTestId("receipt-panel");
    await expect(panel).toContainText("已标 3 处要改");
    await page.locator("#p-5").scrollIntoViewIfNeeded();
    await shot(page, "2-标了要改", browserName, false);

    // 底部条不挡最后一页的「这页要改」
    await page.locator("#p-6").getByRole("button", { name: "这页要改" }).scrollIntoViewIfNeeded();
    const btn = await page.locator("#p-6").getByRole("button", { name: "这页要改" }).boundingBox();
    const bar = await panel.boundingBox();
    expect(btn && bar && btn.y + btn.height <= bar.y).toBeTruthy();

    await panel.getByRole("button", { name: /提交修改意见/ }).click();
    const sheet = page.getByRole("dialog", { name: "提交修改意见" });
    await expect(sheet).toContainText("第 2 页");
    await expect(sheet).toContainText("第 5 页");
    await expect(sheet).toContainText("整体");
    await shot(page, "3-提交前核对", browserName, false);
    await sheet.getByRole("button", { name: /确认提交/ }).click();
    await expect(page.getByText("修改意见收到了，改好的一版还在这一页看。").first()).toBeVisible();
    await expect(page.getByText("改稿单交给做 PPT 的同事了")).toBeVisible();
    await shot(page, "4-提交以后", browserName, false);
  });

  test("确认收货后在同一页下载最终版", async ({ page, browserName }) => {
    const t = all[browserName];
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/d/${t.confirm}`);
    await page.getByTestId("receipt-panel").getByRole("button", { name: "确认收货" }).click();
    const dlg = page.getByRole("dialog", { name: "确认收货" });
    await expect(dlg).toContainText("之后不支持退款");
    await shot(page, "5-确认收货弹窗", browserName, false);
    await dlg.getByRole("button", { name: "确认收货" }).click();
    await expect(page.getByRole("heading", { name: "可编辑的 PPT 和讲稿" })).toBeVisible();
    await expect(page.getByRole("link", { name: "下载" })).toHaveCount(2);
    await expect(page.getByRole("img", { name: /水印版/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /还想改（还剩 1 轮修改）/ })).toBeVisible(); // 含的一轮没用，确认后照样能用
    await shot(page, "6-最终版", browserName);
    const href = await page.getByRole("link", { name: "下载" }).first().getAttribute("href");
    const res = await page.request.get(href ?? "");
    expect(res.status()).toBe(200);
  });

  test("手机：平台单、点开看原大、不横向滚动", async ({ page, browserName }) => {
    const t = all[browserName];
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/d/${t.platform}`);
    await expect(page.getByTestId("receipt-panel")).toContainText("闲鱼");
    await expect(page.getByRole("button", { name: "我已经在闲鱼点了" })).toBeVisible();
    await expect(page.getByRole("button", { name: "确认收货" })).toHaveCount(0);
    await noSideScroll(page);
    await shot(page, "7-手机平台单", browserName, false);
    await page.getByRole("button", { name: "看第 1 页原大" }).click();
    const big = page.getByRole("img", { name: "第 1 页原大（水印版）" });
    await expect(big).toBeVisible();
    expect(await big.evaluate((el: HTMLImageElement) => el.getBoundingClientRect().width)).toBeGreaterThan(1000);
    await shot(page, "8-手机看原大", browserName, false);
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "我已经在闲鱼点了" }).click();
    await expect(page.getByText("我们核对闲鱼的订单后")).toBeVisible();
  });

  test("手机：已交付的单", async ({ page, browserName }) => {
    const t = all[browserName];
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/d/${t.final}`);
    await expect(page.getByRole("heading", { name: "可编辑的 PPT 和讲稿" })).toBeVisible();
    await noSideScroll(page);
    await page.getByRole("button", { name: /还想改/ }).click();
    await page.getByRole("button", { name: "这页要改" }).click();
    await page.getByLabel("第 1 页要改什么").fill("封面标题换成中文");
    await expect(page.getByTestId("receipt-panel")).toContainText("用掉 1 轮");
    await shot(page, "9-手机已交付后再改", browserName);
  });
});
