/**
 * 全站唯一发请求的地方（scripts/check.py 第 1 条：别处不许直接 fetch）。
 *
 * - 基址 /api：开发时 Vite 代理到后端，生产时后端自己同域提供。
 * - 带 cookie（后台登录靠它）。
 * - 非 2xx 一律抛 ApiError，message 是后端 detail 里的中文说明。
 *
 * 区块取数：在区块文件夹的 load.ts 里调这里的函数，组件只吃 props。
 */

export const API_BASE = "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(status: number, message: string, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

export interface RequestOptions extends Omit<RequestInit, "body"> {
  /** 查询参数；值为 null / undefined 的会被跳过 */
  query?: Query;
  /** JSON 请求体（自动 JSON.stringify 并设 Content-Type） */
  json?: unknown;
  /** 表单 / 文件上传（不要自己设 Content-Type） */
  form?: FormData;
}

function buildUrl(path: string, query?: Query): string {
  const p = path.startsWith("/") ? path : `/${path}`;
  const url = `${API_BASE}${p}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== null && v !== undefined) params.append(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

function messageFrom(status: number, body: unknown): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return "提交的内容格式不对";
  }
  if (status === 401) return "请先登录";
  if (status === 404) return "没有找到";
  if (status >= 500) return "服务器出错了，请稍后再试";
  return `请求失败（${status}）`;
}

export async function api<T = unknown>(path: string, options: RequestOptions = {}): Promise<T> {
  const { query, json, form, headers, ...init } = options;
  const h = new Headers(headers);
  let body: BodyInit | undefined;
  if (json !== undefined) {
    h.set("Content-Type", "application/json");
    body = JSON.stringify(json);
  } else if (form) {
    body = form;
  }
  h.set("Accept", "application/json");

  let res: Response;
  try {
    res = await fetch(buildUrl(path, query), { credentials: "same-origin", ...init, headers: h, body });
  } catch (e) {
    throw new ApiError(0, "网络连不上，请检查网络后再试", e);
  }

  if (res.status === 204) return undefined as T;
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data: unknown = isJson ? await res.json().catch(() => null) : await res.text();
  if (!res.ok) throw new ApiError(res.status, messageFrom(res.status, data), data);
  return data as T;
}

export const apiGet = <T = unknown>(path: string, query?: Query, init?: RequestOptions) =>
  api<T>(path, { ...init, method: "GET", query });

export const apiPost = <T = unknown>(path: string, json?: unknown, init?: RequestOptions) =>
  api<T>(path, { ...init, method: "POST", json });

export const apiUpload = <T = unknown>(path: string, form: FormData, init?: RequestOptions) =>
  api<T>(path, { ...init, method: "POST", form });
