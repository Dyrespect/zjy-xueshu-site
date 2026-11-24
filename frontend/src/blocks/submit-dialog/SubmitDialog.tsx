import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { errorText, Field, FormError, Honeypot, ImagePicker } from "@/blocks/figure-forms";
import type { Done, SubmissionDraft } from "@/lib/figures-types";

export interface SubmitFormProps {
  onSubmit: (draft: SubmissionDraft) => Promise<Done>;
  onDone: (message: string) => void;
}

/** 投图：一张图 + 出处（必填）+ 为什么觉得好 + 署名。进后台待审，不直接上库 */
export function SubmitForm({ onSubmit, onDone }: SubmitFormProps) {
  const [image, setImage] = useState<File | null>(null);
  const [source, setSource] = useState("");
  const [reason, setReason] = useState("");
  const [credit, setCredit] = useState("");
  const [website, setWebsite] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!image) return setError("选一张图");
    if (!source.trim()) return setError("写上这张图的出处（DOI 或论文题目）");
    setPending(true);
    setError("");
    try {
      const r = await onSubmit({ image, source: source.trim(), reason: reason.trim(), credit: credit.trim(), website });
      setImage(null);
      setSource("");
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
          <Field label="图片">
            <ImagePicker file={image} onChange={setImage} maxMb={10} onTooLarge={setError} />
          </Field>
          <Field label="出处" htmlFor="sb-source" hint="DOI 或论文题目">
            <Input id="sb-source" value={source} onChange={(e) => setSource(e.target.value)} maxLength={500} placeholder="10.1037/apl0000494" />
          </Field>
          <Field label="为什么觉得好" optional htmlFor="sb-reason">
            <Textarea id="sb-reason" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} rows={2} placeholder="比如：三个研究的关系一眼能看懂" />
          </Field>
          <Field label="署名" optional htmlFor="sb-credit" hint="收录后显示「由 XX 推荐」">
            <Input id="sb-credit" value={credit} onChange={(e) => setCredit(e.target.value)} maxLength={40} />
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

export interface SubmitDialogProps extends Omit<SubmitFormProps, "onDone"> {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export function SubmitDialog({ open, onOpenChange, onSubmit }: SubmitDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>推荐一张更好的同类图</DialogTitle>
          <DialogDescription>我们审核后收进图库，详情页会写上你的署名。</DialogDescription>
        </DialogHeader>
        <SubmitForm
          onSubmit={onSubmit}
          onDone={(message) => {
            toast.success(message);
            onOpenChange(false);
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
