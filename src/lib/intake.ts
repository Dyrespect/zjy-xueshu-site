/**
 * 客户这边的接口：网页聊天（/api/channels/web/*）。交付页（/api/delivery/*）在 lib/delivery.ts。
 * 只通过 api.ts 发请求；区块的 load.ts 调这里。
 */
import { apiGet, apiPost, apiUpload } from "./api";
import type { ChatMessage, WebChat } from "./intake-types";

export * from "./intake-types";

const KEY_STORE = "xshb.chat.key";

export function rememberedChatKey(): string | null {
  try {
    return window.localStorage.getItem(KEY_STORE);
  } catch {
    return null;
  }
}

export function rememberChatKey(key: string): void {
  try {
    window.localStorage.setItem(KEY_STORE, key);
  } catch {
    /* 隐私模式存不了也没关系，地址栏里的就是凭证 */
  }
}

export const newChatSession = () => apiPost<{ key: string }>("/channels/web/sessions");
export const getChat = (key: string) => apiGet<WebChat>(`/channels/web/${encodeURIComponent(key)}`);
export const sendChatText = (key: string, text: string) =>
  apiPost<ChatMessage>(`/channels/web/${encodeURIComponent(key)}/messages`, { text });
export function sendChatFile(key: string, file: File) {
  const form = new FormData();
  form.append("file", file);
  return apiUpload<ChatMessage>(`/channels/web/${encodeURIComponent(key)}/files`, form);
}

// 交付页的取数在 lib/delivery.ts（模块 E）


