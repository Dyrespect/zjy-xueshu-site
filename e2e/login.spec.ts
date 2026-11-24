import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test, type Browser, type Page } from "@playwright/test";

// 登录走查（docs/任务单/12_登录与正规化_设计.md 第十六节）：WebKit 手机宽 390，微信 UA 和普通手机浏览器 UA 各走
// 「认领 → 我的订单」「手机号绑定」，另截营业执照页和电脑上的扫码登录框。后端要开假微信、假短信：
//   WECHAT_MP_FAKE=true SMS_FAKE=true SMS_DEV_DIR=<目录> bash scripts/dev.sh
// 再造码：.venv/bin/python scripts/entry_walkthrough_seed.py <json>（跑两次，两份）
//   LOGIN_CODES=<第一份> LOGIN_CODES2=<第二份> SMS_DIR=<SMS_DEV_DIR> SHOT_DIR=<截图文件夹> pnpm e2e --project=webkit e2e/login.spec.ts
const codes = process.env.LOGIN_CODES ? JSON.parse(readFileSync(process.env.LOGIN_CODES, "utf-8")) : null;
const codes2 = process.env.LOGIN_CODES2 ? JSON.parse(readFileSync(process.env.LOGIN_CODES2, "utf-8")) : null;
const smsDir = process.env.SMS_DIR;
const shotDir = process.env.SHOT_DIR;
const PHONE = { width: 390, height: 844 };
const WECHAT_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 "
  + "MicroMessenger/8.0.50(0x18003237) NetType/WIFI Language/zh_CN";
const MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
  + "Mobile/15E148 Safari/604.1";

async function shot(page: Page, name: string, fullPage = true) {
  if (!shotDir) return;
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${shotDir}/${name}.png`, fullPage });
}

async function noSideScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

function lastSmsCode(phone: string): string {
  if (!smsDir) throw new Error("没给 SMS_DIR");
  const tail = phone.slice(-4);
  const files = readdirSync(smsDir).filter((f) => f.endsWith(`-${tail}.txt`)).sort();
  const text = readFileSync(join(smsDir, files[files.length - 1]), "utf-8");
  return /^(\d{6})为您的登录验证码/m.exec(text)![1];
}

/** 每次走查换一个号（同一个号连着跑会撞上 60 秒、每天的发送上限） */
const rnd = () => String(Math.floor(1000 + Math.random() * 8999));
const WX_PHONE = `1380000${rnd()}`;
const M_PHONE = `1390000${rnd()}`;

async function phoneCtx(browser: Browser, ua: string) {
  const ctx = await browser.newContext({ viewport: PHONE, userAgent: ua, deviceScaleFactor: 2, isMobile: true, hasTouch: true, locale: "zh-CN" });
  return { ctx, page: await ctx.newPage() };
}

async function fillPhone(page: Page, phone: string, scope = "login") {
  await page.locator(`#${scope}-number`).fill(phone);
  await page.getByRole("button", { name: "获取验证码" }).click();
  await expect(page.getByText(/验证码发到 .* 了/)).toBeVisible();
  await page.locator(`#${scope}-code`).fill(lastSmsCode(phone));
}

test.describe("登录", () => {
  test.skip(!codes || !smsDir, "没给 LOGIN_CODES / SMS_DIR");

  test("微信里：自动登录 → 认领 → 需求卡顶上绑手机号 → 我的订单", async ({ browser, browserName }) => {
    test.setTimeout(90_000);
    const c = codes[browserName];
    const { ctx, page } = await phoneCtx(browser, WECHAT_UA);
    await page.goto(`/c/${c.paid}`);
    // 静默授权（假微信）跳一圈回到兑换页，已经登录了
    await expect(page.getByTestId("redeem-account")).toContainText("已登录：微信");
    await expect(page.getByTestId("redeem-login-step")).toHaveCount(0);
    await noSideScroll(page);
    await shot(page, "wx-1-兑换页-已自动登录");
    await page.getByTestId("redeem-action-entry.webchat").click();
    await expect(page).toHaveURL(/\/b\/[A-Za-z0-9_-]{16,}/);
    await expect(page.getByTestId("phone-bind")).toBeVisible();
    await noSideScroll(page);
    await shot(page, "wx-2-需求卡-提示绑手机号", false);
    await fillPhone(page, WX_PHONE, "bind");
    await page.getByRole("button", { name: "绑定" }).click();
    await expect(page.getByTestId("phone-bound")).toContainText("绑好了");
    await shot(page, "wx-3-需求卡-绑好了", false);
    await page.goto("/me");
    await expect(page.getByTestId("my-account")).toContainText(`微信 · 手机 138****${WX_PHONE.slice(-4)}`);
    await expect(page.getByTestId("my-order")).toHaveCount(1);
    await expect(page.getByTestId("phone-bind")).toHaveCount(0);
    await noSideScroll(page);
    await shot(page, "wx-4-我的订单");
    await ctx.close();
  });

  test("手机浏览器：兑换页第一步手机号登录 → 认领 → 我的订单；别的设备打开交付页提示登录", async ({ browser, browserName }) => {
    test.setTimeout(90_000);
    const c = codes[browserName];
    const { ctx, page } = await phoneCtx(browser, MOBILE_UA);
    await page.goto(`/c/${c.unclaimed}`);
    await expect(page.getByTestId("redeem-login-step")).toBeVisible();
    await expect(page.getByTestId("redeem-action-entry.webchat")).toHaveCount(0); // 没登录不给认领按钮
    await noSideScroll(page);
    await shot(page, "m-1-兑换页-第一步登录");
    await fillPhone(page, M_PHONE);
    await shot(page, "m-2-兑换页-填了验证码");
    await page.getByRole("button", { name: "登录", exact: true }).click();
    await expect(page.getByTestId("redeem-account")).toContainText(`手机 139****${M_PHONE.slice(-4)}`);
    await shot(page, "m-3-兑换页-登录后认领到我的账号");
    await page.getByTestId("redeem-action-entry.webchat").click();
    await expect(page).toHaveURL(/\/b\//);
    await expect(page.getByTestId("phone-bind")).toHaveCount(0); // 用手机号登录的，不再提示绑
    await page.goto("/me");
    await expect(page.getByTestId("my-account")).toContainText(`手机 139****${M_PHONE.slice(-4)}`);
    await expect(page.getByTestId("my-order")).toHaveCount(1);
    await noSideScroll(page);
    await shot(page, "m-4-我的订单");
    // 交付页老链接照样能开；已经是自己的，不出「登录后记到账号」那一条
    await page.getByRole("link", { name: "交付页" }).first().click();
    await expect(page).toHaveURL(/\/d\//);
    await expect(page.getByTestId("account-banner")).toHaveCount(0);
    await ctx.close();
    // 另一个手机浏览器打开同一个交付页、没登录：顶上提示登录
    const other = await phoneCtx(browser, MOBILE_UA);
    await other.page.goto(page.url());
    await expect(other.page.getByTestId("account-banner")).toContainText("登录后");
    await shot(other.page, "m-5-交付页-别的设备没登录-提示登录", false);
    await other.ctx.close();
  });

  for (const [who, ua] of [["wx", WECHAT_UA], ["m", MOBILE_UA]] as const) {
    test(`营业执照页（页脚链接、执照图、文字）· ${who === "wx" ? "微信" : "手机浏览器"}`, async ({ browser }) => {
      const { ctx, page } = await phoneCtx(browser, ua);
      await page.goto("/");
      await page.getByTestId("footer-license").first().click();
      await expect(page).toHaveURL(/\/license$/);
      await expect(page.getByRole("heading", { name: "营业执照" })).toBeVisible();
      await expect(page.getByTestId("license-info")).toContainText("91330110MAKFUNHCXY");
      await expect(page.getByTestId("license-info")).toContainText("杭州市余杭区市场监督管理局");
      await expect(page.getByTestId("license-image")).toBeVisible();
      await noSideScroll(page);
      await shot(page, `lic-${who}-营业执照`);
      await ctx.close();
    });
  }

  test("电脑：扫码登录（假二维码 + 模拟扫码）", async ({ browser, browserName }) => {
    test.skip(!codes2, "没给 LOGIN_CODES2");
    const c = codes2[browserName];
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 860 }, locale: "zh-CN" });
    const page = await ctx.newPage();
    await page.goto(`/c/${c.paid}`);
    await expect(page.getByTestId("login-qr").locator("img")).toBeVisible();
    await shot(page, "pc-1-兑换页-扫码登录", false);
    await page.getByRole("button", { name: "模拟手机扫码（本机走查）" }).click();
    await expect(page.getByTestId("redeem-account")).toContainText("微信扫码", { timeout: 10_000 });
    await shot(page, "pc-2-扫码后已登录", false);
    await ctx.close();
  });
});
