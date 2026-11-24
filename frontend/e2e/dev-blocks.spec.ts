import { expect, test } from "@playwright/test";

// 截图：SHOT=../docs/截图/xxx.png pnpm e2e --project=chromium
test("区块陈列页摆出了页头和页脚", async ({ page }) => {
  await page.goto("/dev/blocks");
  await expect(page.getByRole("heading", { name: "区块陈列" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "站点页头" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "站点页脚" })).toBeVisible();
  await expect(page.getByRole("link", { name: "汇报 PPT 定制" }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "意见反馈" }).first()).toBeVisible();
  if (process.env.SHOT) await page.screenshot({ path: process.env.SHOT, fullPage: true });
});

test("手机宽度不横向滚动", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/dev/blocks");
  await expect(page.getByRole("heading", { name: "区块陈列" })).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
});

test("没有的地址显示页面不存在", async ({ page }) => {
  await page.goto("/没有这一页");
  await expect(page.getByRole("heading", { name: "页面不存在" })).toBeVisible();
});
