import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { errorText, Field, FormError, Honeypot } from "@/blocks/figure-forms";
import type { Done } from "@/lib/figures-types";
import type { TakedownDraft } from "@/lib/site-types";

export interface TakedownFormProps {
  /** 多少小时内下架（后台聚人设置，默认 48） */
  hours: number;
  onSubmit: (d: TakedownDraft) => Promise<Done>;
  onDone: (message: string) => void;
}

/** 版权方要求删除：哪几张图（网址或图号）、权利人、联系方式、理由。收到马上通知负责人，限时内从网站和下一版图库包里撤。 */
export function TakedownForm({ hours, onSubmit, onDone }: TakedownFormProps) {
  const [figures, setFigures] = useState("");
  const [holder, setHolder] = useState("");
  const [contact, setContact] = useState("");
  const [reason, setReason] = useState("");
  const [website, setWebsite] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!figures.trim()) return setError("写上是哪几张图（图的网址或图号）");
    if (!contact.trim()) return setError("留一个联系方式，处理结果发给你");
    setPending(true);
    setError("");
    try {
      const r = await onSubmit({ figures: figures.trim(), holder: holder.trim(), contact: contact.trim(), reason: reason.trim(), website });
      setFigures("");
      setReason("");
      onDone(r.message);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} className="relative flex flex-col gap-5">
      <p className="text-[15px] leading-relaxed text-body">
        网站上的图来自公开发表的论文，每张都写了出处，版权归原作者和期刊。你是权利人、不希望某张图出现在这里，告诉我们，{hours}{" "}
        小时内从网站和下一版图库包里撤下。
      </p>
      <Field label="哪几张图" htmlFor="td-figures" hint="图详情页的网址，或者图号，一行一张">
        <Textarea id="td-figures" value={figures} onChange={(e) => setFigures(e.target.value)} maxLength={2000} rows={3} />
      </Field>
      <Field label="权利人" optional htmlFor="td-holder" hint="期刊、出版社或作者">
        <Input id="td-holder" value={holder} onChange={(e) => setHolder(e.target.value)} maxLength={200} />
      </Field>
      <Field label="联系方式" htmlFor="td-contact" hint="邮箱或电话">
        <Input id="td-contact" value={contact} onChange={(e) => setContact(e.target.value)} maxLength={200} />
      </Field>
      <Field label="说明" optional htmlFor="td-reason">
        <Textarea id="td-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={2000} rows={3} />
      </Field>
      <Honeypot value={website} onChange={setWebsite} />
      <FormError message={error} />
      <div className="flex justify-end">
        <Button type="submit" disabled={pending}>
          {pending ? "提交中…" : "提交"}
        </Button>
      </div>
    </form>
  );
}
