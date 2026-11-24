import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

// 开票走查（docs/任务单/07_开票_设计.md 第八节第 3 条）：下单页勾「需要发票」→ 核对 → 假网关付款 → 付款页看到草稿；
// 交付页申请、核对、看进度、下载；平台单的说明；后台发票页（复制、上传开好的发票、作废重开、设置）；手机宽度。
// 要先造好单子：INVOICE_TOKENS=<scripts/invoice_walkthrough_seed.py 写的 json> ADMIN_PASSWORD=<本机密码> SHOT_DIR=<截图文件夹>
//   pnpm e2e e2e/invoice.spec.ts
// 没给 INVOICE_TOKENS 就跳过（这几条会改订单和发票，不能对着随便哪个库跑；后端要开假网关 SHOP_FAKE_PAY）。
const tokensFile = process.env.INVOICE_TOKENS;
const shotDir = process.env.SHOT_DIR;
const password = process.env.ADMIN_PASSWORD ?? "";
type Tokens = Record<string, { apply: string; issued: string; waiting: string; platform: string; queued: string; queued_title: string }>;
const all: Tokens = tokensFile ? JSON.parse(readFileSync(tokensFile, "utf-8")) : {};
const PDF = Buffer.from("%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n");

async function shot(page: Page, name: string, browser: string, fullPage = false) {
  if (!shotDir) return;
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${shotDir}/${browser}-${name}.png`, fullPage });
}

async function noSideScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

/** 下单页付款前的三项确认（站点整合加的，不勾不让付款） */
async function agreeConsent(page: Page) {
  const box = page.locator("[data-consent]").filter({ visible: true });
  for (const name of ["terms_privacy", "ai_processing", "custom_no_refund"]) await box.locator(`input[name="${name}"]`).check();
}

async function fillInvoice(page: Page, prefix: string, taxId: string) {
  await page.locator(`#${prefix}-title`).fill("清华大学");
  await page.locator(`#${prefix}-tax_id`).fill(taxId);
  await page.locator(`#${prefix}-email`).fill("lab@example.edu.cn");
}

test.describe("开票", () => {
  test.skip(!tokensFile, "没给 INVOICE_TOKENS");

  test("下单页勾需要发票、核对、付款后付款页看到草稿", async ({ page, browserName }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/order");
    const section = page.getByRole("region", { name: "发票" });
    await expect(section).toBeVisible();
    await section.getByText("需要发票", { exact: true }).click();
    await fillInvoice(page, "order-inv", "12100000400000624"); // 少一位
    await agreeConsent(page);
    await expect(page.getByTestId("order-total").filter({ visible: true })).toBeVisible();
    await page.getByRole("button", { name: "去付款" }).filter({ visible: true }).first().click();
    await expect(section.getByText("税号是 15、18 或 20 位，现在是 17 位")).toBeVisible();
    await section.scrollIntoViewIfNeeded();
    await shot(page, "01-下单页-税号位数不对", browserName);

    await page.locator("#order-inv-tax_id").fill("12100000400000624D");
    await page.getByRole("button", { name: "去付款" }).filter({ visible: true }).first().click();
    const dlg = page.getByRole("dialog", { name: "核对发票信息" });
    await expect(dlg).toContainText("12100000400000624D");
    await expect(dlg).toContainText("开出后改不了");
    await shot(page, "02-下单页-核对弹窗", browserName);
    await dlg.getByRole("button", { name: "核对无误，去付款" }).click();

    await expect(page).toHaveURL(/\/order\/pay\//);
    await page.getByRole("button", { name: "模拟付款" }).click();
    await expect(page.getByTestId("activation-code")).toBeVisible();
    const panel = page.getByTestId("invoice-panel");
    await expect(panel).toContainText("订单完成（确认收货）后自动提交开票");
    await expect(panel).toContainText("清华大学");
    await panel.scrollIntoViewIfNeeded();
    await shot(page, "03-付款页-发票草稿", browserName, true);
  });

  test("交付页申请发票、核对、看进度", async ({ page, browserName }) => {
    const t = all[browserName];
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/d/${t.apply}`);
    const panel = page.getByTestId("invoice-panel");
    await expect(panel).toBeVisible();
    await panel.getByRole("button", { name: "申请发票" }).click();
    await fillInvoice(page, "inv-delivery", "12100000400000624A"); // 最后一位抄错：前端只查位数，后端按国标校验
    await panel.getByRole("button", { name: "下一步：核对" }).click();
    let dlg = page.getByRole("dialog", { name: "核对发票信息" });
    await dlg.getByRole("button", { name: "核对无误，提交" }).click();
    await expect(panel.getByText(/最后一位校验不对/)).toBeVisible();
    await shot(page, "04-交付页-税号校验位不对", browserName);
    await page.locator("#inv-delivery-tax_id").fill("12100000400000624D");
    await panel.getByRole("button", { name: "下一步：核对" }).click();
    dlg = page.getByRole("dialog", { name: "核对发票信息" });
    await shot(page, "05-交付页-核对弹窗", browserName);
    await dlg.getByRole("button", { name: "核对无误，提交" }).click();
    await expect(panel).toContainText("已提交，等待开票");
    await expect(panel.getByRole("button", { name: "信息填错了，撤回重填" })).toBeVisible();
    await shot(page, "06-交付页-待开票", browserName);
  });

  test("交付页下载开好的发票；没完成的先填好；平台单的说明", async ({ page, browserName }) => {
    const t = all[browserName];
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto(`/d/${t.issued}`);
    const panel = page.getByTestId("invoice-panel");
    await expect(panel).toContainText("发票开好了");
    const link = panel.getByRole("link", { name: "下载" });
    await expect(link).toHaveCount(1);
    const res = await page.request.get((await link.getAttribute("href")) ?? "");
    expect(res.status()).toBe(200);
    expect((await res.body()).subarray(0, 5).toString()).toBe("%PDF-");
    await shot(page, "07-交付页-已开票", browserName);

    await page.goto(`/d/${t.waiting}`);
    await expect(page.getByTestId("invoice-panel")).toContainText("订单完成（确认收货）后自动提交开票，现在可以先填好");
    await page.goto(`/d/${t.platform}`);
    await expect(page.getByTestId("invoice-panel")).toContainText("这单是在小红书下的，发票请在下单的平台申请");
    await shot(page, "08-交付页-平台单", browserName);
  });

  test("手机宽度：下单页发票一节、交付页发票", async ({ page, browserName }) => {
    const t = all[browserName];
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/d/${t.issued}`);
    await page.getByTestId("invoice-panel").scrollIntoViewIfNeeded();
    await noSideScroll(page);
    await shot(page, "09-手机-交付页已开票", browserName);
    await page.goto("/order");
    const section = page.getByRole("region", { name: "发票" });
    await section.getByText("需要发票", { exact: true }).click();
    await section.scrollIntoViewIfNeeded();
    await noSideScroll(page);
    await shot(page, "10-手机-下单页发票", browserName);
  });

  test("后台发票页：复制、上传开好的发票、作废重开、设置", async ({ page, browserName, context }) => {
    test.skip(!password, "没给 ADMIN_PASSWORD");
    if (browserName === "chromium") await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto("/admin/login");
    await page.getByLabel("密码").fill(password);
    await page.getByRole("button", { name: /登录/ }).click();
    await page.goto("/admin/invoices");
    await expect(page.getByRole("heading", { name: "发票" })).toBeVisible();
    await expect(page.getByTestId("invoice-metrics")).toContainText("开票申请率");
    const title = all[browserName].queued_title;
    const row = page.locator("tr", { hasText: title });
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: "复制抬头信息" }).click();
    await expect(row.getByText("复制好了")).toBeVisible();
    await shot(page, "11-后台-待开票", browserName);

    await row.getByRole("button", { name: "开好了，上传" }).click();
    const dlg = page.getByRole("dialog", { name: "上传开好的发票" });
    await expect(dlg).toContainText("纳税人识别号：91330110MAKFUNHCXY");
    await dlg.getByLabel("发票文件").setInputFiles({ name: "发票.pdf", mimeType: "application/pdf", buffer: PDF });
    await shot(page, "12-后台-上传弹窗", browserName);
    await dlg.getByRole("button", { name: "标记已开" }).click();
    await expect(dlg).toBeHidden();

    await page.getByRole("tab", { name: /已开票/ }).click();
    const issued = page.getByRole("tabpanel").locator("tr", { hasText: title });
    await expect(issued).toContainText("已开票");
    await issued.getByRole("button", { name: "作废 / 重开" }).click();
    const vd = page.getByRole("dialog", { name: "作废发票" });
    await vd.getByLabel("原因").fill("抬头少了「学部」两个字（走查）");
    await shot(page, "13-后台-作废重开弹窗", browserName);
    await vd.getByRole("button", { name: "作废并重开" }).click();
    await expect(vd).toBeHidden();
    await page.getByRole("tab", { name: /待开票/ }).click();
    await expect(page.getByRole("tabpanel").locator("tr", { hasText: title })).toBeVisible();

    await page.getByRole("tab", { name: "设置" }).click();
    await expect(page.getByText("待财务确认").first()).toBeVisible();
    await expect(page.getByRole("textbox", { name: "开票项目名称" })).toHaveValue("技术服务费");
    await expect(page.getByRole("combobox", { name: "纳税人类型" })).toHaveValue("小规模纳税人");
    await shot(page, "14-后台-设置", browserName, true);
  });
});
