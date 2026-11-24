import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

// 需求引导走查（docs/任务单/09_需求引导_方案.md「验收」）：兑换页认领 → 需求卡全部按推荐（1 分钟内）→ 选样张 → 确认卡 →
// 对，开工 → 订单进制作中；后台订单详情里看需求卡、代客人确认；下单页多了那一句。Chromium + WebKit，手机 390 和桌面。
// 会生成码、认领、改订单，只对着本机走查用的新库跑（每天开工名额 3 单，同一个库跑两遍第一条会排到明天、进不了制作中）：
//   ADMIN_PASSWORD=<本机密码> SHOT_DIR=<截图文件夹> FRONTEND_PORT=<前端端口> pnpm e2e e2e/brief.spec.ts
const password = process.env.ADMIN_PASSWORD ?? "";
const shotDir = process.env.SHOT_DIR;
const MOBILE = { width: 390, height: 844 };
const DESKTOP = { width: 1280, height: 900 };
const PDF = Buffer.from("%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n");

async function shot(page: Page, name: string, browser: string, fullPage = true) {
  if (!shotDir) return;
  await page.waitForTimeout(400);
  await page.screenshot({ path: `${shotDir}/${browser}-${name}.png`, fullPage });
}

async function noSideScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(0);
}

/** 流程页的精简页脚：一行公司全称、ICP 备案号、用户协议、隐私政策；不挂全站四栏链接 */
async function slimFooter(page: Page) {
  const legal = page.getByTestId("site-legal");
  await expect(legal).toContainText("有限公司");
  await expect(legal).toContainText("ICP备");
  await expect(legal.getByRole("link", { name: "用户协议" })).toBeVisible();
  await expect(legal.getByRole("link", { name: "隐私政策" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "页脚导航" })).toHaveCount(0);
}

/** 平台单（后台生成的码）第一次确认：确认卡上勾三项（协议、AI 处理和出境、定制不退）才能开工 */
async function tickConsents(page: Page) {
  const box = page.locator("[data-consent]");
  await expect(box).toContainText("开工前请确认");
  for (const k of ["terms_privacy", "ai_processing", "custom_no_refund"]) await box.locator(`input[name="${k}"]`).check();
}

const CONSENTS = { consents: ["terms_privacy", "ai_processing", "custom_no_refund"], terms_version: "2026-11-18", privacy_version: "2026-11-18" };

async function login(req: APIRequestContext) {
  expect((await req.post("/api/auth/login", { data: { password } })).ok()).toBeTruthy();
}

async function newCode(req: APIRequestContext, sku = "regular-p1"): Promise<string> {
  const r = await req.post("/api/admin/intake/codes/generate", { data: { sku, count: 1 } });
  return (await r.json()).codes[0];
}

async function orderOf(req: APIRequestContext, token: string) {
  const v = await (await req.get(`/api/channels/brief/${token}`)).json();
  const oid = Number(v.order_no);
  const rows = await (await req.get("/api/admin/intake/orders")).json();
  const cid = rows.find((r: { id: number }) => r.id === oid).customer_id as number;
  return { oid, cid };
}

async function stage(req: APIRequestContext, cid: number): Promise<string> {
  return (await (await req.get(`/api/admin/intake/conversations/${cid}`)).json()).order.stage;
}

test.describe("需求引导", () => {
  test.skip(!password, "没给 ADMIN_PASSWORD");

  test("认领 → 需求卡全部按推荐 → 选样张 → 确认卡 → 对，开工 → 制作中", async ({ page, browserName }) => {
    test.setTimeout(120_000);
    const req = page.request;
    await login(req);
    const code = await newCode(req);
    await page.setViewportSize(MOBILE);
    await page.goto(`/c/${code}`);
    await page.getByTestId("redeem-action-entry.webchat").click();
    await expect(page).toHaveURL(/\/b\/[A-Za-z0-9_-]{16,}/);
    const token = page.url().split("/b/")[1];
    const key = await page.evaluate(() => window.localStorage.getItem("xshb.chat.key"));
    const { cid } = await orderOf(req, token);

    // 认领后的两个入口：兑换页（是你的）第一个按钮、聊天顶上一条
    await page.goto(`/c/${code}`);
    await expect(page.getByRole("heading", { name: "这单已经在你这里" })).toBeVisible();
    await expect(page.getByTestId("redeem-action-brief")).toBeVisible();
    await slimFooter(page);
    await noSideScroll(page);
    await shot(page, "01-认领后入口-兑换页-手机", browserName);
    await page.goto(`/chat/${key}`);
    await expect(page.getByTestId("chat-brief")).toContainText("还没确认");
    await shot(page, "02-认领后入口-聊天顶上-手机", browserName, false);

    // 客人在聊天里交了论文；助手记下的事实这里由后台填（走查不调模型）
    await req.post(`/api/channels/web/${key}/files`, { multipart: { file: { name: "Affiliation in human-AI interactions.pdf", mimeType: "application/pdf", buffer: PDF } } });
    const conv = await (await req.get(`/api/admin/intake/conversations/${cid}`)).json();
    const oid = conv.order.id as number;
    await req.post(`/api/admin/intake/orders/${oid}/files/${conv.order.materials[0].id}/purpose`, { data: { purpose: "论文" } });
    const day = new Date(Date.now() + 8 * 86400_000).toISOString().slice(0, 10);
    await req.patch(`/api/admin/intake/orders/${oid}`, { data: { occasion: "组会文献", present_date: day } });
    expect(await stage(req, cid)).toBe("collecting"); // 资料齐了，需求卡没确认：不开工

    // 需求卡：一题一屏，全部「不知道，按推荐做」
    await page.goto(`/b/${token}`);
    await expect(page.getByRole("heading", { name: "这次是什么场合" })).toBeVisible();
    await slimFooter(page);
    await noSideScroll(page);
    await shot(page, "03-需求卡-第一题-手机", browserName);
    const t0 = Date.now();
    for (let i = 0; i < 7; i++) {
      const before = await page.getByTestId("brief-progress").textContent();
      if (i === 2) await shot(page, "04-需求卡-讲多久-手机", browserName);
      await page.getByRole("radio", { name: /不知道，按推荐做/ }).click();
      await expect(page.getByTestId("brief-progress")).not.toHaveText(before ?? "");
    }
    // 看样张选风格
    await expect(page.getByRole("heading", { name: /看几份样张/ })).toBeVisible();
    await page.getByRole("radio", { name: /色块标题/ }).click();
    await expect(page.getByRole("radio", { name: /色块标题/ })).toHaveAttribute("aria-checked", "true");
    await noSideScroll(page);
    await shot(page, "05-选样张-手机", browserName);
    await page.getByTestId("brief-next").click();
    // 传旧材料（可不传）
    await page.getByTestId("brief-upload-ref").setInputFiles({ name: "上次组会.pptx", mimeType: "application/vnd.openxmlformats-officedocument.presentationml.presentation", buffer: Buffer.from("PK\x03\x04deck") });
    await expect(page.getByText("上次组会.pptx")).toBeVisible();
    await shot(page, "06-传旧材料-手机", browserName);
    await page.getByTestId("brief-next").click();
    // 确认卡
    await expect(page.getByTestId("brief-card")).toBeVisible();
    await expect(page.getByTestId("brief-card")).toContainText("最像「色块标题");
    await noSideScroll(page);
    await shot(page, "07-确认卡-手机", browserName);
    await page.getByTestId("brief-confirm").click(); // 没勾同意：不往下走，标出没勾的
    await expect(page.getByText("还有没勾的，勾上才能开工。")).toBeVisible();
    await tickConsents(page);
    await shot(page, "07b-确认卡-勾了同意-手机", browserName);
    await page.getByTestId("brief-confirm").click();
    await expect(page.getByTestId("brief-confirmed")).toBeVisible();
    const secs = (Date.now() - t0) / 1000;
    expect(secs).toBeLessThan(60);
    await shot(page, "08-确认了-手机", browserName);
    await expect.poll(() => stage(req, cid)).toBe("making"); // 对，开工 → 制作中
    await page.setViewportSize(DESKTOP);
    await shot(page, "09-确认了-桌面", browserName);
    await page.goto(`/chat/${key}`);
    await expect(page.getByTestId("chat-brief")).toContainText("已确认");
    console.log(`${browserName}：需求卡从第一题到点「对，开工」用了 ${secs.toFixed(1)} 秒`);
  });

  test("第一题上方「全部按推荐」→ 直接到确认卡 → 点一行回去改完回确认卡 → 对，开工", async ({ page, browserName }) => {
    const req = page.request;
    await login(req);
    const code = await newCode(req);
    await page.setViewportSize(MOBILE);
    await page.goto(`/c/${code}`);
    await page.getByTestId("redeem-action-entry.webchat").click();
    await expect(page).toHaveURL(/\/b\//);
    const token = page.url().split("/b/")[1];
    const quick = page.getByTestId("brief-all-default");
    await expect(quick).toHaveText(/全部按推荐，直接看确认卡/);
    await shot(page, "18-第一题上方-全部按推荐-手机", browserName, false);
    await quick.click();
    const card = page.getByTestId("brief-card");
    await expect(card).toBeVisible();
    const rows = card.locator("dd");
    await expect(rows).toHaveCount(9);
    for (let i = 0; i < 8; i++) await expect(rows.nth(i)).toContainText("按推荐"); // 最后一行是参考材料
    await noSideScroll(page);
    await shot(page, "19-全部按推荐-确认卡-手机", browserName);
    // 点「听众」那一行回去改，选完直接回确认卡
    await card.getByRole("button", { name: "改听众" }).click();
    await page.getByRole("radio", { name: /答辩评委/ }).click();
    await expect(card).toBeVisible();
    await expect(card).toContainText("答辩评委");
    await expect(rows.nth(1)).not.toContainText("按推荐");
    await shot(page, "20-改了一行回确认卡-手机", browserName);
    await tickConsents(page);
    await page.getByTestId("brief-confirm").click();
    await expect(page.getByTestId("brief-confirmed")).toBeVisible();
    const { oid } = await orderOf(req, token);
    const adm = await (await req.get(`/api/admin/brief/orders/${oid}`)).json();
    expect(adm.card_text).toContain("场合：组会读文献（按推荐）"); // 后台照常标「按推荐」
    expect(adm.card_text).toContain("听众：答辩评委");
  });

  test("需求卡桌面版、轻量档时长不超出档位", async ({ page, browserName }) => {
    const req = page.request;
    await login(req);
    const code = await newCode(req, "light-p1");
    await page.setViewportSize(DESKTOP);
    const r = await (await req.post(`/api/channels/redeem/${code}/web`, { data: {} })).json();
    await page.goto(r.brief_path);
    await expect(page.getByRole("heading", { name: "这次是什么场合" })).toBeVisible();
    await shot(page, "10-需求卡-第一题-桌面", browserName);
    await page.getByRole("radio", { name: /^开题/ }).click();
    await page.getByRole("radio", { name: /答辩评委/ }).click();
    await expect(page.getByRole("heading", { name: "讲多久" })).toBeVisible();
    await expect(page.getByRole("radio", { name: "20 分钟" })).toHaveCount(0); // 轻量档最多 15 分钟：不能超出档位
    await shot(page, "11-讲多久-轻量档-桌面", browserName);
  });

  test("后台订单详情：需求卡、代客人确认", async ({ page, browserName }) => {
    const req = page.request;
    await login(req);
    const code = await newCode(req);
    const r = await (await req.post(`/api/channels/redeem/${code}/web`, { data: {} })).json();
    const token = r.brief_path.split("/b/")[1];
    await req.put(`/api/channels/brief/${token}`, { data: { answers: { occasion: { choice: "proposal" }, minutes: { choice: "20" }, avoid: { choice: ["wordy", "cartoon"] } } } });
    const { cid } = await orderOf(req, token);
    await page.setViewportSize(DESKTOP);
    await page.goto(`/admin/conversations/${cid}`);
    const panel = page.getByTestId("brief-admin");
    await expect(panel).toBeVisible();
    await expect(panel).toContainText("等客人确认");
    await expect(panel).toContainText("开题");
    await shot(page, "12-后台-订单详情-需求卡", browserName, false);
    // 客人本人还没勾过同意（含出境）：不能代确认
    await expect(page.getByTestId("brief-proxy")).toBeDisabled();
    await expect(page.getByTestId("brief-consent-needed")).toContainText("本人单独同意");
    // 客人自己勾了同意点过一次「对，开工」；你改了一处发回，客人在聊天里说「可以」→ 代确认
    let v = await (await req.get(`/api/channels/brief/${token}`)).json();
    const rest = Object.fromEntries(
      v.settings.questions.filter((q: { key: string; optional: boolean }) => !q.optional && !(q.key in v.answers)).map((q: { key: string }) => [q.key, { choice: "__default__" }]),
    );
    v = await (await req.put(`/api/channels/brief/${token}`, { data: { answers: rest } })).json();
    expect((await req.post(`/api/channels/brief/${token}/confirm`, { data: { version: v.version, ...CONSENTS } })).ok()).toBeTruthy();
    const { oid } = await orderOf(req, token);
    expect((await req.put(`/api/admin/brief/orders/${oid}`, { data: { answers: { minutes: { choice: "15" } }, send_back: true, note: "时长改成 15 分钟" } })).ok()).toBeTruthy();
    await page.reload();
    await expect(panel).toContainText("15 分钟");
    await page.getByTestId("brief-proxy").click();
    await page.getByLabel("代确认的依据").fill("客人在聊天里说「可以，就这样」");
    await shot(page, "13-后台-代确认-写依据", browserName, false);
    await page.getByTestId("brief-proxy-confirm").click();
    await expect(page.getByTestId("brief-admin-status")).toContainText("你代客人确认的");
    await expect(panel).toContainText("依据：客人在聊天里说「可以，就这样」");
    await shot(page, "14-后台-代确认后", browserName, false);
    // 客人那边看到「负责人代你确认了」
    await page.setViewportSize(MOBILE);
    await page.goto(r.brief_path);
    await expect(page.getByTestId("brief-confirmed")).toContainText("负责人按你在聊天里说的代你确认了");
    await shot(page, "15-客人看代确认-手机", browserName);
  });

  test("下单页多了一句、后台设置里能改需求卡", async ({ page, browserName }) => {
    await page.setViewportSize(DESKTOP);
    await page.goto("/order");
    await expect(page.getByTestId("order-brief-note")).toHaveText("付款后我们会一步步引导你说清楚需求，不用提前想好");
    await shot(page, "16-下单页-一句话", browserName, false);
    await login(page.request);
    await page.goto("/admin/settings");
    await expect(page.getByTestId("brief-settings")).toBeVisible();
    await page.getByTestId("brief-settings").evaluate((el) => el.parentElement?.scrollIntoView({ block: "start" }));
    await shot(page, "17-后台设置-需求卡", browserName, false);
  });
});
