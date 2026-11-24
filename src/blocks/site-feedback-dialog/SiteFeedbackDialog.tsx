import { useState, type FormEvent } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { errorText, Field, FormError, Honeypot } from "@/blocks/figure-forms";
import { RequestForm } from "@/blocks/request-dialog";
import type { Done, RequestDraft } from "@/lib/figures-types";

export interface SiteFeedbackDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 当前页面地址（一起交，方便看是哪一页的意见） */
  page: string;
  onRequest: (draft: RequestDraft) => Promise<Done>;
  onSiteFeedback: (body: { content: string; contact: string; page: string; website: string }) => Promise<Done>;
}

function SiteForm({ page, onSubmit, onDone }: { page: string; onSubmit: SiteFeedbackDialogProps["onSiteFeedback"]; onDone: (m: string) => void }) {
  const [content, setContent] = useState("");
  const [contact, setContact] = useState("");
  const [website, setWebsite] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!content.trim()) return setError("写一句你的意见");
    setPending(true);
    setError("");
    try {
      const r = await onSubmit({ content: content.trim(), contact: contact.trim(), page, website });
      setContent("");
      onDone(r.message);
    } catch (err) {
      setError(errorText(err));
    } finally {
      setPending(false);
    }
  }

  return (
    <form onSubmit={submit} className="relative flex flex-col gap-5">
      <Field label="你的意见" htmlFor="sf-content">
        <Textarea
          id="sf-content"
          value={content}
          onChange={(e) => setContent(e.target.value)}
          maxLength={1000}
          rows={4}
          placeholder="比如：希望能按期刊和年份筛"
          required
        />
      </Field>
      <Field label="怎么联系你" optional htmlFor="sf-contact" hint="微信号或邮箱，需要回复时用">
        <Input id="sf-contact" value={contact} onChange={(e) => setContact(e.target.value)} maxLength={100} />
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

/** 页头「意见反馈」：两件事分开填——找不到想要的图（提需求），对网站本身的意见 */
export function SiteFeedbackDialog({ open, onOpenChange, page, onRequest, onSiteFeedback }: SiteFeedbackDialogProps) {
  const done = (message: string) => {
    toast.success(message);
    onOpenChange(false);
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>意见反馈</DialogTitle>
        </DialogHeader>
        <Tabs defaultValue="request" className="gap-5">
          <TabsList className="w-full">
            <TabsTrigger value="request">找不到想要的图</TabsTrigger>
            <TabsTrigger value="site">对网站的意见</TabsTrigger>
          </TabsList>
          <TabsContent value="request">
            <RequestForm onSubmit={onRequest} onDone={done} />
          </TabsContent>
          <TabsContent value="site">
            <SiteForm page={page} onSubmit={onSiteFeedback} onDone={done} />
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
