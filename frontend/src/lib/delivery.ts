/**
 * 交付页的接口（/api/delivery/*，模块 E）。只通过 api.ts 发请求；页面和区块的 load.ts 调这里。
 */
import { apiGet, apiPost, apiUpload } from "./api";
import type { ConfirmResult, DeliveryData, RevisionDraft, RevisionResult, Satisfaction } from "./delivery-types";
import type { OkMessage } from "./intake-types";

export * from "./delivery-types";

const base = (token: string) => `/delivery/${encodeURIComponent(token)}`;

export const getDelivery = (token: string) => apiGet<DeliveryData>(base(token));

/** 逐页提修改：每条带自己的附件，提交时附件按顺序放进 files，条目里记下标。 */
export function submitRevision(token: string, drafts: RevisionDraft[], basedOnRound: number) {
  const form = new FormData();
  const files: File[] = [];
  const items = drafts
    .filter((d) => d.text.trim())
    .map((d) => {
      const idx = d.files.map((f) => files.push(f) - 1);
      return { page: d.page, text: d.text.trim(), files: idx };
    });
  form.append("items", JSON.stringify(items));
  form.append("based_on_round", String(basedOnRound));
  for (const f of files) form.append("files", f);
  return apiUpload<RevisionResult>(`${base(token)}/revision`, form);
}

export const confirmReceived = (token: string) => apiPost<ConfirmResult>(`${base(token)}/received`);
export const claimPlatformConfirmed = (token: string) => apiPost<OkMessage>(`${base(token)}/platform-confirmed`);
export const markViewed = (token: string, round: number, pages: number) =>
  apiPost<OkMessage>(`${base(token)}/viewed`, { round, pages });
export const sendFeedback = (token: string, body: { satisfaction: Satisfaction; comment: string; share_revised: boolean }) =>
  apiPost<OkMessage>(`${base(token)}/feedback`, body);
