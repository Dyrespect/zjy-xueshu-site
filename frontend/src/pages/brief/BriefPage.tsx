import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { AccountBannerBox } from "@/blocks/account-banner/load";
import { BriefCard } from "@/blocks/brief-card";
import { CheckoutConsent } from "@/blocks/checkout-consent";
import { FlowFrame } from "@/blocks/flow-shell/load";
import { PhoneBindBox } from "@/blocks/phone-bind/load";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  confirmBrief,
  getBrief,
  removeBriefFile,
  saveBrief,
  uploadBriefFile,
  DEFAULT_CHOICE,
  type BriefAnswer,
  type BriefAnswers,
  type BriefView,
} from "@/lib/brief";
import { getSession, type AccountSession } from "@/lib/account";
import { POLICY_VERSIONS } from "@/lib/site-pages";
import { CONSENT_KEYS, type ConsentKey } from "@/lib/website";

const NO_CONSENT: Record<ConsentKey, boolean> = { terms_privacy: false, ai_processing: false, custom_no_refund: false };

function scrollToConsent() {
  document.querySelector<HTMLElement>("[data-consent]")?.scrollIntoView({ behavior: "smooth", block: "center" });
}

/** 「全部按推荐」：每一题（可选的也算）和样张都记成按推荐 */
function allDefault(view: BriefView): BriefAnswers {
  const out: BriefAnswers = Object.fromEntries(view.settings.questions.map((q) => [q.key, { choice: DEFAULT_CHOICE }]));
  if (view.settings.style.samples.length) out.style = { choice: DEFAULT_CHOICE };
  return out;
}

/**
 * /b/:token 需求卡（09 需求引导）：认领以后点选场合、听众、时长、语言、模板、重点、不要什么，看样张选风格，传旧材料，
 * 最后对着确认卡点「对，开工」。没确认不开工。页头跟全站一样、页脚精简一行（blocks/flow-shell）；地址带令牌，不让收录。
 * 还没勾过同意的单（小红书、闲鱼这类平台单，view.consent_needed）：确认卡上勾三项（协议、AI 处理和出境、定制不退）才能开工，
 * 随「对，开工」带给后端（后端没勾全 422，出境要本人单独同意）。自有网页单下单时勾过，这里不再勾。
 */
export function BriefPage() {
  const { token = "" } = useParams();
  const navigate = useNavigate();
  const [view, setView] = useState<BriefView | null>(null);
  const [missing, setMissing] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [consent, setConsent] = useState<Record<ConsentKey, boolean>>(NO_CONSENT);
  const [showMissing, setShowMissing] = useState(false);
  const [session, setSession] = useState<AccountSession | null>(null);

  // 12 号设计：顶上「登录后记到你的账号」；登录了、没绑手机号、短信开着 → 提示绑一次（可先不绑）
  useEffect(() => {
    getSession().then(setSession, () => setSession(null));
  }, [token]);

  useEffect(() => {
    getBrief(token)
      .then(setView)
      .catch((e) => setMissing(e instanceof ApiError ? e.message : "打不开，稍后再试"));
  }, [token]);

  const run = useCallback(async (fn: () => Promise<BriefView>) => {
    setBusy(true);
    setError("");
    try {
      setView(await fn());
    } catch (e) {
      setError(e instanceof Error ? e.message : "没存上，再试一次");
      throw e;
    } finally {
      setBusy(false);
    }
  }, []);

  return (
    <FlowFrame className="text-base">
      {view ? (
        <div className="mx-auto flex max-w-3xl flex-col gap-3 px-4 pt-6 sm:px-6">
          <AccountBannerBox token={token} />
          {session?.logged_in && session.sms && session.prompt_phone ? (
            <PhoneBindBox onSkipped={() => setSession({ ...session, prompt_phone: false })} />
          ) : null}
        </div>
      ) : null}
      {view ? (
        <BriefCard
          view={view}
          busy={busy}
          error={error}
          onAnswer={(key: string, answer: BriefAnswer) => run(() => saveBrief(token, { [key]: answer }))}
          onUpload={(file, kind) => run(() => uploadBriefFile(token, file, kind)).catch(() => undefined)}
          onRemoveFile={(id) => run(() => removeBriefFile(token, id)).catch(() => undefined)}
          onConfirm={() => {
            if (!view.consent_needed) return run(() => confirmBrief(token, view.version)).catch(() => undefined);
            if (CONSENT_KEYS.some((k) => !consent[k])) {
              setShowMissing(true);
              scrollToConsent();
              return Promise.resolve();
            }
            const body = { consents: CONSENT_KEYS, terms_version: POLICY_VERSIONS.terms, privacy_version: POLICY_VERSIONS.privacy };
            return run(() => confirmBrief(token, view.version, body)).catch(() => undefined);
          }}
          consent={
            view.consent_needed ? (
              <CheckoutConsent
                checked={consent}
                onChange={(k, v) => setConsent((c) => ({ ...c, [k]: v }))}
                revisions={view.revisions_included ?? 1}
                showMissing={showMissing}
                legend="开工前请确认（三项都勾上才能开工）"
                missingText="还有没勾的，勾上才能开工。"
              />
            ) : undefined
          }
          onAllDefault={() => run(() => saveBrief(token, allDefault(view)))}
          onChat={view.chat_path ? () => navigate(view.chat_path as string) : undefined}
        />
      ) : missing ? (
        <div className="mx-auto flex max-w-md flex-col items-center gap-4 px-4 py-20 text-center">
          <h1 className="text-xl font-semibold text-foreground">{missing}</h1>
          <p className="text-sm text-body">从订单的聊天里重新点一次需求卡的链接。</p>
          <Button variant="outline" onClick={() => navigate("/c")}>
            用激活码找回订单
          </Button>
        </div>
      ) : (
        <p className="mx-auto max-w-xl px-4 py-16 text-sm text-muted-foreground sm:px-6">正在打开需求卡……</p>
      )}
    </FlowFrame>
  );
}
