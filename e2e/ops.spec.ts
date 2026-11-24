import { expect, test, type Page } from "@playwright/test";

// 运维页走查（docs/任务单/07_运维与数据_设计.md 第八节第 7 条）：总览、错误与告警、备份（现在备份、恢复演练）、飞书汇报、设置；手机宽度不横向滚动。
// 要后台密码：ADMIN_PASSWORD=<本机密码> SHOT_DIR=<截图文件夹（不进 git）> pnpm e2e e2e/ops.spec.ts
// 没给 ADMIN_PASSWORD 就跳过（会真跑一次本机备份，不能对着随便哪个库跑）。
const password = process.env.ADMIN_PASSWORD ?? "";
const shotDir = process.env.SHOT_DIR;

async function shot(page: Page, name: string, browser: string, fullPage = true) {
  if (!shotDir) return;
  await page.waitForTimeout(500);
  await page.screenshot({ path: `${shotDir}/${browser}-${name}.png`, fullPage });
}

async function noSideScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

async function login(page: Page) {
  await page.goto("/admin/login?next=/admin/ops");
  await page.locator("input[type=password]").fill(password);
  await page.keyboard.press("Enter");
  await page.waitForURL("**/admin/ops**");
}

test.describe("运维", () => {
  test.skip(!password, "没给 ADMIN_PASSWORD");

  test("总览、错误与告警、备份、飞书汇报、设置", async ({ page, browserName }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await login(page);
    await expect(page.getByRole("heading", { name: "运维" })).toBeVisible();
    await expect(page.getByTestId("ops-overview")).toContainText("关键数字");
    await expect(page.getByTestId("ops-health")).toContainText("数据库可写");
    await expect(page.getByRole("link", { name: "运维" })).toHaveAttribute("aria-current", "page");
    await shot(page, "ops-1-总览", browserName);

    await page.getByRole("tab", { name: /错误与告警/ }).click();
    await expect(page).toHaveURL(/tab=errors/);
    await expect(page.getByTestId("ops-errors")).toContainText("最近的错误");
    await shot(page, "ops-2-错误与告警", browserName);

    await page.getByRole("tab", { name: "备份" }).click();
    await page.getByRole("button", { name: "现在备份" }).click();
    await expect(page.getByText("备份好了")).toBeVisible({ timeout: 30_000 });
    await page.getByRole("button", { name: "现在做恢复演练" }).click();
    await expect(page.getByText(/恢复演练过了/)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("ops-backups")).toContainText("恢复出来都对得上");
    await shot(page, "ops-3-备份", browserName);

    await page.getByRole("tab", { name: "飞书汇报" }).click();
    await expect(page.getByTestId("ops-report-preview")).toContainText("有没有要你处理的问题");
    // 没配机器人：试发、现在发都是灰的
    await expect(page.getByRole("button", { name: "试发一条" })).toBeDisabled();
    await shot(page, "ops-4-飞书汇报", browserName);

    await page.getByRole("tab", { name: "设置" }).click();
    await expect(page.getByTestId("ops-settings")).toContainText("客户数据保存期限");
    await expect(page.getByTestId("ops-settings")).toContainText("待财务确认");
    await shot(page, "ops-5-设置", browserName);
  });

  test("手机宽度不横向滚动；飞书链接直接到页签", async ({ page, browserName }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page);
    await expect(page.getByTestId("ops-overview")).toBeVisible();
    await noSideScroll(page);
    await shot(page, "ops-6-手机总览", browserName);
    await page.goto("/admin/ops?tab=backups");
    await expect(page.getByTestId("ops-backups")).toBeVisible();
    await noSideScroll(page);
    await page.goto("/admin/ops?tab=report");
    await expect(page.getByTestId("ops-report")).toBeVisible();
    await noSideScroll(page);
    await shot(page, "ops-7-手机飞书汇报", browserName);
  });
});
