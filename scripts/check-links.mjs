#!/usr/bin/env node
/**
 * 统一站点链接检查（模块 L）：官网 ↔ 下单页 ↔ 兑换页 ↔ 图库，所有页头页脚链接都通。
 *
 * 用法（frontend/ 下；服务先起好）：
 *   SITE_MAIN_URL=http://127.0.0.1:8731 SITE_APP_URL=http://127.0.0.1:5174 SITE_FIGURES_URL=http://127.0.0.1:5174 \
 *     node scripts/check-links.mjs
 * 线上：三个变量换成正式域名（和后端 .env 的 SITE_* 一样）。
 *
 * 为什么不用 lychee / linkchecker：图库、下单、兑换都是前端渲染的页面（React），HTML 里没有链接，
 * 只抓 HTML 的检查器看不见页头页脚；这里用仓库里已有的 Playwright 打开页面再取链接。页面清单来自站点地图，不乱爬。
 *
 * 查三样，失败信息都写三件（错在哪、怎么改、看哪份）：
 *   1. 站点地图里每块的起点页能打开（状态码 < 400、不是「页面不存在」）；
 *   2. 每一页都有去「汇报 PPT 定制」「心理学科研图库」两组每一项的链接，页脚有公司全称和备案号；
 *   3. 页面上指向这三块的链接都能打开（详情、浏览、搜索这类同一种页面各抽 3 个）。
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

const here = dirname(fileURLToPath(import.meta.url));
const MAP_FILE = process.env.SITE_MAP ?? resolve(here, "../../backend/app/gather/site_map.json");
const MAP_DOC = "backend/app/gather/site_map.json；docs/任务单/07_科研绘图聚人_设计.md 第六节第 7 条";
const OFFICIAL_FIX = "官网是 psyppt 静态站：在 学术汇报/docs/方案/2026-11-18_生态顶层设计/psyppt静态站/build.py 的 NAV 和 site_footer 里加上（改法见 docs/任务单/07_科研绘图聚人_官网补丁.diff）";
const map = JSON.parse(readFileSync(MAP_FILE, "utf-8"));
const bases = {
  main: (process.env.SITE_MAIN_URL ?? "").replace(/\/$/, ""),
  app: (process.env.SITE_APP_URL ?? "").replace(/\/$/, ""),
  figures: (process.env.SITE_FIGURES_URL ?? "").replace(/\/$/, ""),
};
const failures = [];
const fail = (where, what, fix, see = MAP_DOC) => failures.push({ where, what, fix, see });

for (const [k, v] of Object.entries(bases)) {
  if (!/^https?:\/\//.test(v)) {
    console.error(`[失败] 没给 SITE_${k === "main" ? "MAIN" : k === "app" ? "APP" : "FIGURES"}_URL（要以 http 开头）\n    怎么改：照文件开头的用法把三块的网址都给上\n    看哪份：${MAP_DOC}`);
    process.exit(2);
  }
}

function norm(u) {
  try {
    const x = new URL(u);
    let p = x.pathname.replace(/\/index\.html$/, "/");
    if (p.length > 1) p = p.replace(/\/$/, "");
    return `${x.origin}${p}`;
  } catch {
    return u;
  }
}
const sectionOf = (u) => {
  const n = norm(u);
  // 同一个地址前缀可能是好几块（本机开发时下单页和图库同一个前端）：按路径认
  for (const [k, b] of Object.entries(bases)) {
    if (!n.startsWith(b)) continue;
    if (k === "main" && (/\.html$/.test(n) || n === b || n === `${b}/`)) return "main";
  }
  return Object.entries(bases).find(([, b]) => n.startsWith(b))?.[0] ?? null;
};
const expected = map.groups
  .filter((g) => map.required_groups.includes(g.key))
  .flatMap((g) => g.items.map((it) => ({ group: g.title, label: it.label, url: bases[it.section] + it.path, section: it.section })));

let company = "杭州竹涧云科技有限公司";
let icp = "浙ICP备";
try {
  const r = await fetch(`${bases.figures}/api/gather/site`);
  if (r.ok) ({ company, icp } = await r.json());
} catch {
  /* 拿不到就用默认的两样字 */
}

const browser = await chromium.launch();
const page = await (await browser.newContext({ locale: "zh-CN" })).newPage();
const opened = new Map(); // norm(url) -> 结果

async function open(url) {
  const key = norm(url);
  if (opened.has(key)) return opened.get(key);
  let res = { ok: false, status: 0, text: "", links: [] };
  try {
    const resp = await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
    await page.waitForTimeout(300);
    const text = await page.evaluate(() => document.body.innerText);
    const links = await page.evaluate(() => Array.from(document.querySelectorAll("a[href]"), (a) => ({ href: a.href, text: a.textContent.trim() })));
    const status = resp ? resp.status() : 0;
    res = { ok: status > 0 && status < 400 && !text.includes(map.not_found_text), status, text, links };
  } catch (e) {
    res.error = String(e).slice(0, 160);
  }
  opened.set(key, res);
  return res;
}

const starts = Object.entries(map.pages).flatMap(([sec, paths]) => paths.map((p) => ({ sec, url: bases[sec] + p })));
const toVisit = new Map();
for (const s of starts) {
  const r = await open(s.url);
  if (!r.ok) {
    fail(s.url, `起点页打不开（状态 ${r.status}${r.error ? `，${r.error}` : ""}${r.text.includes(map.not_found_text) ? "，显示「页面不存在」" : ""}）`,
      s.sec === "main" ? "确认官网静态站在 SITE_MAIN_URL 上、这一页存在" : "确认前端路由里有这一页（frontend/src/pages/**/routes.tsx）、服务起着");
    continue;
  }
  const have = new Set(r.links.map((l) => norm(l.href)));
  for (const e of expected) {
    if (!have.has(norm(e.url))) {
      fail(s.url, `页面上没有去「${e.group} · ${e.label}」的链接（应指向 ${e.url}）`,
        s.sec === "main" ? OFFICIAL_FIX : "页头页脚用 blocks/site-header、site-footer，链接从 /api/gather/site 来；检查 .env 的 SITE_* 三个网址");
    }
  }
  if (!r.text.includes(company) || !r.text.includes(icp)) {
    fail(s.url, `页脚缺公司全称或备案号（要有「${company}」和「${icp}」）`, s.sec === "main" ? OFFICIAL_FIX : "页脚用 blocks/site-footer，company、icp 从站点地图来");
  }
  for (const l of r.links) {
    const sec = sectionOf(l.href);
    if (sec) toVisit.set(norm(l.href), { url: l.href, from: s.url, text: l.text });
  }
}

// 同一种页面（详情、浏览、搜索、兑换）各抽 3 个
const family = (u) => new URL(u).pathname.replace(/\/[^/]+$/, "/*");
const perFamily = new Map();
let external = 0;
for (const [key, l] of toVisit) {
  const path = new URL(l.url).pathname;
  if (/^\/(figure|types|c|search)\b/.test(path)) {
    const f = family(l.url);
    const n = perFamily.get(f) ?? 0;
    if (n >= 3) continue;
    perFamily.set(f, n + 1);
  }
  const r = await open(l.url);
  if (!r.ok) {
    fail(l.from, `链接「${l.text || key}」打不开：${l.url}（状态 ${r.status}${r.text.includes(map.not_found_text) ? "，显示「页面不存在」" : ""}）`,
      "改成存在的地址；站点地图里的路径和前端路由、官网文件名要对上");
  }
}
for (const r of opened.values()) external += r.links.filter((l) => !sectionOf(l.href) && /^https?:/.test(l.href)).length;
await browser.close();

console.log(`查了 ${starts.length} 个起点页、一共打开 ${opened.size} 个页面；站外链接（备案查询这类）${external} 个，没查。`);
if (failures.length) {
  for (const f of failures) console.log(`[失败] ${f.where}\n    错在哪：${f.what}\n    怎么改：${f.fix}\n    看哪份：${f.see}`);
  console.log(`\n链接检查：不通过，${failures.length} 处`);
  process.exit(1);
}
console.log("链接检查：全通");
