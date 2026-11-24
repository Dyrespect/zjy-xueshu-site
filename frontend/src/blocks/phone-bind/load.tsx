import { useState } from "react";

import { skipPhone, startSms, verifySms } from "@/lib/account";

import { PhoneBind } from "./PhoneForm";

export interface PhoneBindBoxProps {
  /** 绑好了（message：「绑好了」或「两边的订单合在一起了」） */
  onDone?: (message: string) => void;
  onSkipped?: () => void;
  compact?: boolean;
  /** 能不能「先不绑」（我的订单里那个不给跳过按钮） */
  skippable?: boolean;
}

/** 自己调接口的绑手机号卡（需求卡顶上、我的订单里用）。页面要先确认短信开着才放它（规矩 23）。 */
export function PhoneBindBox({ onDone, onSkipped, compact, skippable = true }: PhoneBindBoxProps) {
  const [done, setDone] = useState("");
  if (done) {
    return <p className="rounded-lg border px-5 py-4 text-sm text-body" data-testid="phone-bound">{done}</p>;
  }
  return (
    <PhoneBind
      compact={compact}
      onStart={(phone) => startSms(phone, "bind")}
      onVerify={(phone, code) => verifySms(phone, code, "bind").then((r) => {
        setDone(r.message);
        onDone?.(r.message);
      })}
      onSkip={skippable ? () => void skipPhone().finally(() => onSkipped?.()) : undefined}
    />
  );
}
