import { useEffect, useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { errorText, Field, FormError, Honeypot, ImagePicker } from "@/blocks/figure-forms";
import type { Done, RequestDraft } from "@/lib/figures-types";

export interface RequestFormProps {
  /** 刚才搜的那句话：自动填进「想画什么图」，并一起交 */
  query?: string;
  searchId?: number | null;
  onSubmit: (draft: RequestDraft) => Promise<Done>;
  onDone: (message: string) => void;
}

/** 提需求：想画什么图（必填）、研究方向或方法、草图、怎么联系你 */
export function RequestForm({ query = "", searchId = null, onSubmit, onDone }: RequestFormProps) {
  const [want, setWant] = useState(query);
  const [method, setMethod] = useState("");
  const [contact, setContact] = useState("");
  const [sketch, setSketch] = useState<File | null>(null);
  const [website, setWebsite] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => setWant(query), [query]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!want.trim()) {
      setError("写一句想画什么图");
      return;
    }
    setPending(true);
    setError("");
    try {
      const r = await onSubmit({ want: want.trim(), method: method.trim(), contact: contact.trim(), sketch, query, searchId, website });
      setMethod("");
      setContact("");
      setSketch(null);
      onDone(r.message);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} className="relative flex flex-col gap-5">
      <Field label="想画什么图" htmlFor="rq-want">
        <Textarea
          id="rq-want"
          value={want}
          onChange={(e) => setWant(e.target.value)}
          maxLength={300}
          rows={2}
          placeholder="比如：fNIRS 的光极排布图，要标出通道和脑区"
          required
        />
      </Field>
      <Field label="研究方向或用了什么方法" optional htmlFor="rq-method">
        <Input id="rq-method" value={method} onChange={(e) => setMethod(e.target.value)} maxLength={300} placeholder="比如：近红外超扫描，亲子互动" />
      </Field>
      <Field label="草图或别人的例子" optional>
        <ImagePicker file={sketch} onChange={setSketch} maxMb={5} onTooLarge={setError} />
      </Field>
      <Field label="怎么联系你" optional htmlFor="rq-contact" hint="留微信号或邮箱，找到了告诉你">
        <Input id="rq-contact" value={contact} onChange={(e) => setContact(e.target.value)} maxLength={100} />
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

export interface RequestDialogProps extends Omit<RequestFormProps, "onDone"> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function RequestDialog({ open, onOpenChange, ...form }: RequestDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>告诉我们你要画什么</DialogTitle>
          <DialogDescription>我们照着去补图，补上以后搜同样的话就能找到。</DialogDescription>
        </DialogHeader>
        <RequestForm
          {...form}
          onDone={(message) => {
            toast.success(message);
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
