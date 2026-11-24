import { useState } from "react";

import { Button } from "@/components/ui/button";

import { RequestDialog } from "./RequestDialog";

export function RequestDialogDemo({ query }: { query?: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="p-4">
      <Button variant="outline" onClick={() => setOpen(true)}>
        打开「提需求」弹层
      </Button>
      <RequestDialog
        open={open}
        onOpenChange={setOpen}
        query={query}
        onSubmit={async () => ({ message: "收到了。找到合适的图会通过你留的联系方式告诉你。" })}
      />
    </div>
  );
}
