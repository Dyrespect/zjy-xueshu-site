import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Page } from "@playwright/test";

// 入口走查（docs/任务单/07_入口_设计.md 第十节第 4、6 条）：兑换页各种状态（桌面 + 手机宽度）、留在网页做 → 聊天第一条是清单、
// 没认领不收文件、留邮箱、我的订单、后台「入口」页。
// 先造码：ENTRY_CODES=<scripts/entry_walkthrough_seed.py 写的 json> MAIL_DIR=<后端的 EMAIL_DEV_DIR> ADMIN_PASSWORD=<本机密码>
//   SHOT_DIR=<截图文件夹> pnpm e2e e2e/entry.spec.ts
// 没给 ENTRY_CODES 就跳过（这几条会认领码，不能对着随便哪个库跑）。
const codesFile = process.env.ENTRY_CODES;
const mailDir = process.env.MAIL_DIR;
const shotDir = process.env.SHOT_DIR;
const password = process.env.ADMIN_PASSWORD ?? "";
type Codes = Record<string, { unclaimed: string; paid: string; void: string; taken: string }>;
const all: Codes = codesFile ? JSON.parse(readFileSync(codesFile, "utf-8")) : {};
const PDF = Buffer.from("%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n");
const MOBILE = { width: 390, height: 844 };
const DESKTOP = { width: 1280, height: 900 };

async function shot(page: Page, name: string, browser: string, fullPage = true) {
  if (!shotDir) return;
  await page.waitForTimeout(350);
  await page.screenshot({ path: `${shotDir}/${browser}-${name}.png`, fullPage });
}

async function noSideScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

function latestCode(to: string): string {
  if (!mailDir) throw new Error("没给 MAIL_DIR");
  // 两个浏览器同时跑、信写在同一个文件夹：按收件人挑最新的一封
  const texts = readdirSync(mailDir).filter((f) => f.endsWith(".txt")).sort()
    .map((f) => readFileSync(join(mailDir, f), "utf-8")).filter((t) => t.startsWith(`To: ${to}\n`));
  return /验证码是 (\d{6})/.exec(texts[texts.length - 1])![1];
}

test.describe("入口", () => {
  test.skip(!codesFile, "没给 ENTRY_CODES");

  test("兑换页没认领 → 留在网页做 → 聊天第一条是清单 → 留邮箱 → 我的订单", async ({ page, browserName }) => {
    test.setTimeout(90_000); // 一路走完十几步、两个浏览器并行
    const c = all[browserName];
    await page.setViewportSize(DESKTOP);
    await page.goto(`/c/${c.paid}`);
    await expect(page.getByRole("heading", { name: "认领这一单" })).toBeVisible();
    await expect(page.getByTestId("redeem-sku")).toHaveText("长 · 2–3 篇");
    await expect(page.getByText("激活码从哪来")).toBeVisible();
    await shot(page, "01-兑换页-没认领-桌面", browserName);
    await page.setViewportSize(MOBILE);
    await noSideScroll(page);
    await shot(page, "02-兑换页-没认领-手机", browserName);

    await page.getByTestId("redeem-action-entry.webchat").click();
    // 09 需求引导：认领完先到需求卡；聊天地址浏览器记着，/chat 回到它
    await expect(page).toHaveURL(/\/b\/[A-Za-z0-9_-]{16,}/);
    await page.goto("/chat");
    await expect(page).toHaveURL(/\/chat\/[A-Za-z0-9_-]{16,}/);
    await expect(page.getByText(/已对上你的订单/)).toBeVisible();
    await expect(page.getByText(/必需：/)).toBeVisible();
    await expect(page.getByTestId("chat-order")).toContainText("长 · 2–3 篇");
    await noSideScroll(page);
    await shot(page, "03-聊天-认领后第一条是清单-手机", browserName, false);
    await page.setViewportSize(DESKTOP);
    await shot(page, "04-聊天-认领后-桌面", browserName, false);
    const orderNo = /订单 (\d{5})/.exec((await page.getByTestId("chat-order").textContent()) ?? "")![1];

    // 同一个浏览器再打开兑换页：是你的，回到聊天
    const chatUrl = page.url();
    await page.goto(`/c/${c.paid}`);
    await expect(page.getByRole("heading", { name: "这单已经在你这里" })).toBeVisible();
    await shot(page, "05-兑换页-已经在你这里", browserName);
    await page.getByTestId("redeem-action-entry.webchat").click();
    await expect(page).toHaveURL(chatUrl);

    if (mailDir) {
      const email = `walk-${browserName}@example.edu.cn`;
      await page.getByRole("button", { name: "留邮箱，以后凭订单号查" }).click();
      const dlg = page.getByRole("dialog", { name: "留个邮箱（可选）" });
      await dlg.getByLabel("邮箱").fill(email);
      await dlg.getByRole("button", { name: "发验证码" }).click();
      await expect(dlg.getByText(/验证码发到/)).toBeVisible();
      await shot(page, "06-聊天-留邮箱", browserName, false);
      await dlg.getByLabel("验证码").fill(latestCode(email));
      await dlg.getByRole("button", { name: "绑好" }).click();
      await expect(page.getByRole("link", { name: "我的订单" })).toBeVisible();

      await page.goto("/me");
      await page.getByLabel("订单号").fill(orderNo);
      await page.getByLabel("邮箱").fill(email);
      await page.getByRole("button", { name: "发验证码" }).click();
      await expect(page.getByText(/验证码已经发到邮箱了/)).toBeVisible();
      await page.getByLabel("验证码").fill(latestCode(email));
      await page.getByRole("button", { name: "查看订单" }).click();
      await expect(page.getByTestId("my-order").first()).toContainText(orderNo);
      await shot(page, "07-我的订单-桌面", browserName);
      await page.setViewportSize(MOBILE);
      await noSideScroll(page);
      await shot(page, "08-我的订单-手机", browserName);
    }
  });

  test("兑换页的其他状态（手机宽度）", async ({ page, browserName }) => {
    const c = all[browserName];
    await page.setViewportSize(MOBILE);
    await page.goto("/c");
    await expect(page.getByRole("heading", { name: "用激活码认领订单" })).toBeVisible();
    await page.getByRole("textbox", { name: "激活码" }).fill(c.unclaimed.toLowerCase());
    await page.getByRole("button", { name: "查看" }).click();
    await expect(page.getByRole("heading", { name: "认领这一单" })).toBeVisible();
    await shot(page, "11-兑换页-输入码后", browserName);
    await page.goto("/c/PSY-ABCDEFGHJ");
    await expect(page.getByRole("heading", { name: "这个激活码对不上" })).toBeVisible();
    await noSideScroll(page);
    await shot(page, "12-兑换页-码对不上", browserName);
    await page.goto(`/c/${c.void}`);
    await expect(page.getByRole("heading", { name: "这枚激活码已经作废了" })).toBeVisible();
    await shot(page, "13-兑换页-作废", browserName);
    await page.goto(`/c/${c.taken}`);
    await expect(page.getByRole("heading", { name: "这枚激活码已经认领过了" })).toBeVisible();
    await expect(page.getByTestId("redeem-sku")).toHaveCount(0); // 不给陌生人看货号、进度
    await shot(page, "14-兑换页-别人认领了", browserName);
  });

  test("没认领发文件：不收，说一句先发激活码", async ({ page, browserName }) => {
    await page.setViewportSize(MOBILE);
    await page.goto("/chat");
    await expect(page).toHaveURL(/\/chat\/.+/);
    await page.locator('input[type="file"]').setInputFiles({ name: "论文.pdf", mimeType: "application/pdf", buffer: PDF });
    await expect(page.getByText(/先把订单里的激活码发我/)).toBeVisible();
    await shot(page, "21-聊天-没认领不收文件", browserName, false);
  });

  test("后台入口页", async ({ page, browserName }) => {
    test.skip(!password, "没给 ADMIN_PASSWORD");
    await page.setViewportSize(DESKTOP);
    await page.goto("/admin/login");
    await page.getByLabel(/密码/).fill(password);
    await page.getByRole("button", { name: /登录/ }).click();
    await page.waitForURL((u) => !u.pathname.startsWith("/admin/login"));
    await page.goto("/admin/entry");
    await expect(page.getByRole("heading", { name: "入口", exact: true })).toBeVisible();
    await expect(page.getByTestId("wecom-state")).toBeVisible();
    await shot(page, "31-后台-入口", browserName);
  });
});
