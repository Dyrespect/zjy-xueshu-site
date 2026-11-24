import { useState } from "react";

import { Button } from "@/components/ui/button";

import { SiteFeedbackDialog } from "./SiteFeedbackDialog";

export function SiteFeedbackDialogDemo() {
  const [open, setOpen] = useState(false);
  return (
    <div className="p-4">
      <Button variant="outline" onClick={() => setOpen(true)}>
        打开「意见反馈」弹层
      </Button>
      <SiteFeedbackDialog
        open={open}
        onOpenChange={setOpen}
        page="/"
        onRequest={async () => ({ message: "收到了。补到这类图以后，搜同样的话就能找到。" })}
        onSiteFeedback={async () => ({ message: "收到了，谢谢你的意见。" })}
      />
    </div>
  );
}
