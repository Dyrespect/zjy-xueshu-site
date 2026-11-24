/** 接待机器人知识库的后台接口（/api/admin/reception）。只通过 api.ts 发请求。 */
import { api, apiGet, apiPost, apiUpload } from "./api";
import type { ReceptionKB, ReceptionTry } from "./reception-types";

export * from "./reception-types";

export const getReceptionKB = () => apiGet<{ kb: ReceptionKB }>("/admin/reception");
export const saveReceptionKB = (kb: ReceptionKB) => api<{ kb: ReceptionKB }>("/admin/reception", { method: "PUT", json: { kb } });
export const tryReception = (text: string, lastBot: string, reply: string) =>
  apiPost<ReceptionTry>("/admin/reception/try", { text, last_bot: lastBot, reply });

/** 换第 slot 份样张（0–2）：传带水印的 PDF */
export function uploadReceptionSample(slot: number, file: File, title: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("title", title);
  return apiUpload<{ kb: ReceptionKB }>(`/admin/reception/samples/${slot}`, form);
}
