import { useCallback, useEffect, useState } from "react";

import { Container, Note, PageHead, Rows } from "@/blocks/site-section";
import { Button } from "@/components/ui/button";
import { getHealth } from "@/lib/website";

type State = "checking" | "ok" | "down";

const LABEL: Record<State, string> = { checking: "检查中", ok: "正常", down: "异常" };

/**
 * 运行状态：现在只查网站服务本身（/api/health：后端和数据库）。订单、付款、交付等各项服务的状态，
 * 由运维模块接入后放在这一页（这一页是给它留的入口）。
 */
export function StatusPage() {
  const [state, setState] = useState<State>("checking");
  const [at, setAt] = useState<Date | null>(null);
  const check = useCallback(() => {
    setState("checking");
    getHealth()
      .then((h) => setState(h.status === "ok" ? "ok" : "down"))
      .catch(() => setState("down"))
      .finally(() => setAt(new Date()));
  }, []);
  useEffect(check, [check]);
  return (
    <>
      <PageHead eyebrow="关于" title="运行状态" lead="网站服务当前是否正常。遇到问题时，可以先在这里确认。" />
      <Container className="pb-16">
        <Rows
          items={[
            {
              term: "网站服务",
              children: (
                <span data-testid="status-site" className={state === "down" ? "font-medium text-destructive" : "font-medium text-foreground"}>
                  {LABEL[state]}
                </span>
              ),
            },
          ]}
        />
        <Note className="mt-6">
          {at ? `检查时间 ${at.toLocaleString("zh-CN", { hour12: false })}。` : ""}订单、付款、交付等各项服务的状态会陆续接入这一页。
          显示异常而你有急事，请通过「联系我们」页的电话联系我们。
        </Note>
        <div className="mt-6">
          <Button variant="outline" onClick={check} disabled={state === "checking"}>
            重新检查
          </Button>
        </div>
      </Container>
    </>
  );
}
