import { useState } from "react";

import { Button } from "@/components/ui/button";

import { FeedbackDialog } from "./FeedbackDialog";

/** 陈列页用：点按钮打开弹层（提交不发请求） */
export function FeedbackDialogDemo({ query }: { query?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="p-4">
      <Button variant="outline" onClick={() => setOpen(true)}>
        打开「标签不对」弹层
      </Button>
      <FeedbackDialog
        open={open}
        onOpenChange={setOpen}
        query={query}
        onSubmit={async () => ({ message: "收到了，我们会核对这张图的标签。" })}
      />
    </div>
  );
}
