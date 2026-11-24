import { useState } from "react";

import { Button } from "@/components/ui/button";

import { SubmitDialog } from "./SubmitDialog";

export function SubmitDialogDemo() {
  const [open, setOpen] = useState(false);
  return (
    <div className="p-4">
      <Button variant="outline" onClick={() => setOpen(true)}>
        打开「投图」弹层
      </Button>
      <SubmitDialog open={open} onOpenChange={setOpen} onSubmit={async () => ({ message: "收到了。审核通过后收进图库。" })} />
    </div>
  );
}
