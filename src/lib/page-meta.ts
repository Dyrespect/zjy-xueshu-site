import { useEffect } from "react";

function setMeta(name: string, content: string | null) {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[name="${name}"]`);
  if (content === null) {
    el?.remove();
    return;
  }
  if (!el) {
    el = document.createElement("meta");
    el.name = name;
    document.head.appendChild(el);
  }
  el.content = content;
}

/** 这一页的浏览器标题和 <meta name="description">（单页应用：进到哪一页就换哪一页的） */
export function usePageMeta(title: string, description?: string) {
  useEffect(() => {
    if (title) document.title = title;
    if (description) setMeta("description", description);
  }, [title, description]);
}

/** 不让搜索引擎收：noindex = true 时加 <meta name="robots" content="noindex, nofollow">，false 时拿掉 */
export function useRobotsMeta(noindex: boolean | null) {
  useEffect(() => {
    if (noindex === null) return;
    setMeta("robots", noindex ? "noindex, nofollow" : null);
  }, [noindex]);
}
