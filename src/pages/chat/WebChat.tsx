import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { toast } from "sonner";

import { AccountBannerBox } from "@/blocks/account-banner/load";
import { ChatComposer } from "@/blocks/chat-composer";
import { EmailBind } from "@/blocks/email-bind";
import { ChatIntro } from "@/blocks/chat-intro";
import { ChatThread, type ThreadMessage } from "@/blocks/chat-thread";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { startBind, verifyBind } from "@/lib/entry";
import {
  getChat,
  msgTime,
  newChatSession,
  rememberChatKey,
  rememberedChatKey,
  sendChatFile,
  sendChatText,
  type ChatMessage,
  type WebChat as WebChatData,
} from "@/lib/intake";

const ACCEPT = ".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.csv,.png,.jpg,.jpeg,.webp,.txt,.md,.zip,.rar,.7z";

function toThread(m: ChatMessage): ThreadMessage {
  const kind = m.kind === "file" || m.kind === "image" || m.kind === "voice" ? m.kind : "text";
  return {
    id: m.id,
    side: m.sender === "me" ? "right" : "left",
    kind,
    text: m.text,
    card: m.card,
    file: m.file,
    imageUrl: m.image_url,
    time: msgTime(m.created_at),
  };
}

// 开发时 React StrictMode 会把 effect 跑两遍：同一次打开只开一个会话
let starting: Promise<{ key: string }> | null = null;

/** /chat：有存过的就回到原来的聊天，没有就开一个新的。 */
export function ChatStart() {
  const navigate = useNavigate();
  useEffect(() => {
    const k = rememberedChatKey();
    if (k) {
      navigate(`/chat/${k}`, { replace: true });
      return;
    }
    starting = starting ?? newChatSession();
    starting
      .then(({ key }) => {
        rememberChatKey(key);
        navigate(`/chat/${key}`, { replace: true });
      })
      .catch((e) => {
        starting = null;
        toast.error(e instanceof Error ? e.message : "开不了聊天，稍后再试");
      });
  }, [navigate]);
  return null;
}

/** /chat/:key：网页聊天。助手回复、制作方的消息、交付链接都是后台发过来的，所以每几秒刷新一次。 */
export function WebChat() {
  const { key = "" } = useParams();
  const navigate = useNavigate();
  const [data, setData] = useState<WebChatData | null>(null);
  const [missing, setMissing] = useState(false);
  const [binding, setBinding] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const lastCount = useRef(0);

  const load = useCallback(() => {
    getChat(key)
      .then((d) => {
        setData(d);
        rememberChatKey(key);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) setMissing(true);
      });
  }, [key]);

  useEffect(() => {
    load();
    const t = window.setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, 4000);
    return () => window.clearInterval(t);
  }, [load]);

  useEffect(() => {
    const n = data?.messages.length ?? 0;
    if (n !== lastCount.current) {
      lastCount.current = n;
      window.scrollTo({ top: document.documentElement.scrollHeight });
    }
  }, [data]);

  if (missing) {
    return (
      <div className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-4 px-4 text-center">
        <h1 className="text-xl font-semibold text-foreground">这个聊天地址不对，或者已经失效了</h1>
        <Button
          onClick={() =>
            newChatSession().then(({ key: k }) => {
              rememberChatKey(k);
              setMissing(false);
              navigate(`/chat/${k}`, { replace: true });
            })
          }
        >
          开一个新的聊天
        </Button>
      </div>
    );
  }

  const welcome: ThreadMessage[] = data?.welcome
    ? [{ id: "welcome", side: "left", kind: "text", text: data.welcome, time: "" }]
    : [];
  const messages = [...welcome, ...(data?.messages ?? []).map(toThread)];

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <div className="sticky top-0 z-10">
        <ChatIntro
          returnUrl={`${window.location.origin}/chat/${key}`}
          deliveryPath={data?.delivery_path}
          order={data?.order}
          brief={data?.brief}
          account={data?.account_enabled && data.order ? (data.email_bound ? "orders" : "bind") : null}
          onBindEmail={() => setBinding(true)}
          notice={data?.notice}
        />
      </div>
      {data?.account_enabled ? (
        <EmailBind
          open={binding}
          onOpenChange={setBinding}
          onStart={(email) => startBind(key, email)}
          onVerify={(email, code, challenge) => verifyBind(key, email, code, challenge)}
          onDone={(masked) => {
            toast.success(`绑好了：${masked}`);
            load();
          }}
        />
      ) : null}
      <main className="mx-auto w-full max-w-2xl flex-1 px-4 py-5">
        {data?.order ? <AccountBannerBox chatKey={key} className="mb-4" /> : null}
        {data ? <ChatThread messages={messages} /> : null}
        {data?.typing ? (
          <p className="mt-3 text-xs text-muted-foreground" data-testid="chat-typing">
            小鱼正在输入…
          </p>
        ) : null}
        <div ref={bottom} />
      </main>
      <div className="sticky bottom-0 bg-background pb-[max(env(safe-area-inset-bottom),12px)]">
        <div className="mx-auto max-w-2xl px-4 pt-2">
          <ChatComposer
            placeholder="说说汇报：场合、几分钟、哪天"
            accept={ACCEPT}
            onSendText={async (text) => {
              try {
                await sendChatText(key, text);
                load();
              } catch (e) {
                toast.error(e instanceof Error ? e.message : "没发出去");
                throw e;
              }
            }}
            onSendFile={async (file) => {
              try {
                await sendChatFile(key, file);
                load();
              } catch (e) {
                toast.error(e instanceof Error ? e.message : "文件没传上去");
              }
            }}
          />
        </div>
      </div>
    </div>
  );
}
