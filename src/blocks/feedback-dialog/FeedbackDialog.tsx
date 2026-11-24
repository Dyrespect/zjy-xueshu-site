import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { errorText, Field, FormError, Honeypot } from "@/blocks/figure-forms";
import { FEEDBACK_REASONS, type Done } from "@/lib/figures-types";
import { cn } from "@/lib/utils";

export interface FeedbackDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 当时搜的那句话（有就显示，一起交） */
  query?: string;
  onSubmit: (body: { reason: string; note: string; website: string; proposed: { what: string }; credit: string }) => Promise<Done>;
}

/** 「标签不对，我来改」：选一项 + 一句话 + 应该叫什么 + 署名（都选填；审过后详情页写「标签由 XX 改过」） */
export function FeedbackDialog({ open, onOpenChange, query, onSubmit }: FeedbackDialogProps) {
  const [reason, setReason] = useState("");
  const [note, setNote] = useState("");
  const [what, setWhat] = useState("");
  const [credit, setCredit] = useState("");
  const [website, setWebsite] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!reason) {
      setError("选一项哪里不对");
      return;
    }
    setPending(true);
    setError("");
    try {
      const r = await onSubmit({ reason, note: note.trim(), website, proposed: { what: what.trim() }, credit: credit.trim() });
      toast.success(r.message);
      setReason("");
      setNote("");
      setWhat("");
      onOpenChange(false);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>标签不对？你来改</DialogTitle>
          {query ? <DialogDescription>会带上你刚才搜的「{query}」</DialogDescription> : null}
        </DialogHeader>
        <form onSubmit={submit} className="relative flex flex-col gap-5">
          <fieldset className="flex flex-wrap gap-2">
            <legend className="sr-only">哪里不对</legend>
            {FEEDBACK_REASONS.map((r) => (
              <label
                key={r.value}
                className={cn(
                  "cursor-pointer rounded-full border px-3.5 py-1.5 text-sm transition-colors has-[:focus-visible]:ring-[3px] has-[:focus-visible]:ring-ring/40",
                  reason === r.value
                    ? "border-ring bg-highlight text-foreground"
                    : "text-body hover:border-ring/50 hover:text-foreground",
                )}
              >
                <input
                  type="radio"
                  name="reason"
                  value={r.value}
                  checked={reason === r.value}
                  onChange={() => setReason(r.value)}
                  className="sr-only"
                />
                {r.label}
              </label>
            ))}
          </fieldset>
          <Field label="补充一句" optional htmlFor="fb-note">
            <Textarea
              id="fb-note"
              value={note}
              onChange={(e) => setNote(e.target.value)}
              maxLength={500}
              rows={3}
              placeholder="比如：这是实验设计图，不是试次流程"
            />
          </Field>
          <Field label="这张图讲的应该是" optional htmlFor="fb-what" hint="直接写改成什么，审过后网站马上用">
            <Input id="fb-what" value={what} onChange={(e) => setWhat(e.target.value)} maxLength={120} placeholder="比如：亲子互动的近红外超扫描光极排布" />
          </Field>
          <Field label="署名" optional htmlFor="fb-credit" hint="审过后这张图下面写「标签由 XX 改过」">
            <Input id="fb-credit" value={credit} onChange={(e) => setCredit(e.target.value)} maxLength={40} />
          </Field>
          <Honeypot value={website} onChange={setWebsite} />
          <FormError message={error} />
          <div className="flex justify-end">
            <Button type="submit" disabled={pending}>
              {pending ? "提交中…" : "提交"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
