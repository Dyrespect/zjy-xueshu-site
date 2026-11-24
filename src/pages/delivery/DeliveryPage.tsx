import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "react-router";

import { AccountBannerBox } from "@/blocks/account-banner/load";
import { DeliveryFeedback } from "@/blocks/delivery-feedback";
import { DeliveryHead } from "@/blocks/delivery-head";
import { FinalFiles } from "@/blocks/final-files";
import { DeliveryInvoice } from "@/blocks/invoice-panel/load";
import { ProofViewer } from "@/blocks/proof-viewer";
import { ReceiptPanel } from "@/blocks/receipt-panel";
import { RevisionSheet } from "@/blocks/revision-sheet";
import { SiteFrame } from "@/blocks/site-shell/load";
import { Button } from "@/components/ui/button";
import {
  claimPlatformConfirmed,
  confirmReceived,
  getDelivery,
  markViewed,
  sendFeedback,
  submitRevision,
  type DeliveryData,
  type RevisionDraft,
} from "@/lib/delivery";

function useNoIndex() {
  useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex, nofollow";
    document.head.appendChild(meta);
    return () => meta.remove();
  }, []);
}

const DRAFT_KEY = (token: string, round: number) => `xshb.revision.${token}.${round}`;

function loadDrafts(token: string, round: number): RevisionDraft[] {
  try {
    const raw = localStorage.getItem(DRAFT_KEY(token, round));
    const rows = raw ? (JSON.parse(raw) as { key: string; page: number | null; text: string }[]) : [];
    return rows.map((r) => ({ ...r, files: [] }));
  } catch {
    return [];
  }
}

function saveDrafts(token: string, round: number, drafts: RevisionDraft[]) {
  try {
    const rows = drafts.filter((d) => d.text.trim()).map(({ key, page, text }) => ({ key, page, text }));
    if (rows.length) localStorage.setItem(DRAFT_KEY(token, round), JSON.stringify(rows));
    else localStorage.removeItem(DRAFT_KEY(token, round));
  } catch {
    /* 隐私模式存不了：不影响提交 */
  }
}

/** /d/:token 交付页（只有拿到链接的人能看，不进搜索引擎）：逐页看水印版、逐页提修改、确认收货、下载最终版。 */
export function DeliveryPage() {
  const { token = "" } = useParams();
  const [data, setData] = useState<DeliveryData | null>(null);
  const [error, setError] = useState("");
  const [drafts, setDrafts] = useState<RevisionDraft[]>([]);
  const [sheet, setSheet] = useState(false);
  const [busy, setBusy] = useState<"revision" | "confirm" | "claim" | null>(null);
  const [notice, setNotice] = useState("");
  const [sheetError, setSheetError] = useState("");
  const [afterForm, setAfterForm] = useState(false);
  const seen = useRef<{ round: number; max: number; sent: boolean }>({ round: 0, max: 0, sent: false });
  useNoIndex();

  const load = useCallback(() => {
    getDelivery(token)
      .then((d) => {
        setData(d);
        document.title = `${d.title || "汇报 PPT"} · 交付页`;
      })
      .catch((e) => setError(e instanceof Error ? e.message : "打不开"));
  }, [token]);
  useEffect(load, [load]);

  // 草稿按版存在浏览器里（附件存不了），刷新不丢
  const round = data?.revision.based_on_round ?? 0;
  useEffect(() => {
    if (round) setDrafts(loadDrafts(token, round));
  }, [token, round]);
  useEffect(() => {
    if (round) saveDrafts(token, round, drafts);
  }, [token, round, drafts]);

  // 看了几页：翻到底或离开页面时报一次（后台每版每天记一次，申诉举证用）
  const sendSeen = useCallback(() => {
    const s = seen.current;
    if (!s.round || s.sent || !s.max) return;
    s.sent = true;
    markViewed(token, s.round, s.max).catch(() => {});
  }, [token]);
  useEffect(() => {
    const onHide = () => document.visibilityState === "hidden" && sendSeen();
    document.addEventListener("visibilitychange", onHide);
    return () => document.removeEventListener("visibilitychange", onHide);
  }, [sendSeen]);
  const onSeen = useCallback(
    (r: number, max: number) => {
      if (seen.current.round !== r) seen.current = { round: r, max: 0, sent: false };
      seen.current.max = Math.max(seen.current.max, max);
      const total = data?.rounds.find((x) => x.round === r)?.pages.length ?? 0;
      if (total && seen.current.max >= total) sendSeen();
    },
    [data, sendSeen],
  );

  const marked = useMemo(() => drafts.filter((d) => d.text.trim()).length, [drafts]);

  if (error) {
    return (
      <SiteFrame gate={false} noindex cta={false} className="text-base">
        <div className="mx-auto flex min-h-[50vh] max-w-md items-center justify-center px-4 text-center">
          <h1 className="text-xl font-semibold text-foreground">{error}</h1>
        </div>
      </SiteFrame>
    );
  }
  if (!data) return null;

  const showPanel = data.receipt.mode !== "none" || (data.revision.can_submit && marked > 0) || Boolean(notice);
  return (
    <SiteFrame
      gate={false}
      noindex
      cta={false}
      className={showPanel ? "pb-36 text-base" : "text-base"}
      aside={<span className="text-sm text-muted-foreground tabular-nums">单号 {data.order_no}</span>}
    >
      {/* 底下固定着确认收货的面板时，整页（连页脚）往上让出它的高度 */}
      <div className="mx-auto max-w-5xl px-4 pb-16">
        <AccountBannerBox token={token} className="pt-6" />
        <DeliveryHead data={data} />
        <FinalFiles final={data.final} />
        <DeliveryInvoice token={token} />
        {data.revision.can_submit && data.revision.after_delivery && !afterForm ? (
          <div className="mt-8 border-t pt-6">
            <Button variant="outline" size="sm" onClick={() => setAfterForm(true)}>
              还想改（还剩 {data.revision.revisions_left} 轮修改）
            </Button>
          </div>
        ) : null}
        {data.rounds.length || (data.revision.can_submit && (!data.revision.after_delivery || afterForm)) ? (
          <>
            {data.revision.hint ? <p className="mt-6 text-sm text-body">{data.revision.hint}</p> : null}
            <ProofViewer
              rounds={data.rounds}
              canMark={data.revision.can_submit}
              drafts={drafts}
              wholeMax={data.revision.whole_items_max}
              fileMaxMb={data.revision.file_max_mb}
              pageCount={data.revision.page_count}
              onDraftsChange={setDrafts}
              onSeen={onSeen}
            />
          </>
        ) : null}
        {data.show_feedback && !data.feedback_done ? <DeliveryFeedback onSubmit={(body) => sendFeedback(token, body)} /> : null}
      </div>

      {showPanel ? (
        <ReceiptPanel
          receipt={data.receipt}
          revision={data.revision}
          marked={marked}
          busy={busy === "confirm" || busy === "claim" ? busy : null}
          notice={notice}
          onReview={() => {
            setSheetError("");
            setSheet(true);
          }}
          onConfirm={async () => {
            setBusy("confirm");
            try {
              setNotice((await confirmReceived(token)).message);
              load();
            } catch (e) {
              setNotice(e instanceof Error ? e.message : "没确认成功，再试一次");
            } finally {
              setBusy(null);
            }
          }}
          onPlatformClaim={async () => {
            setBusy("claim");
            try {
              setNotice((await claimPlatformConfirmed(token)).message);
            } catch (e) {
              setNotice(e instanceof Error ? e.message : "没发出去，再试一次");
            } finally {
              setBusy(null);
            }
          }}
        />
      ) : null}

      <RevisionSheet
        open={sheet}
        drafts={drafts}
        revisionsLeft={data.revision.revisions_left}
        afterDelivery={data.revision.after_delivery}
        busy={busy === "revision"}
        error={sheetError}
        onOpenChange={setSheet}
        onSubmit={async () => {
          setBusy("revision");
          try {
            const r = await submitRevision(token, drafts, data.revision.based_on_round);
            setDrafts([]);
            saveDrafts(token, data.revision.based_on_round, []);
            setSheet(false);
            setNotice(r.message);
            window.scrollTo({ top: 0, behavior: "smooth" });
            load();
          } catch (e) {
            setSheetError(e instanceof Error ? e.message : "没提交成功，再试一次");
          } finally {
            setBusy(null);
          }
        }}
      />
    </SiteFrame>
  );
}
