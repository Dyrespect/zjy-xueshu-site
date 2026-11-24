import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { UnlockView } from "@/lib/site-types";

import { AllLibraryDialog } from "./AllLibraryDialog";

export function AllLibraryDialogDemo(props: { view: UnlockView | null }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="p-4">
      <Button variant="outline" onClick={() => setOpen(true)}>
        打开「要全部图库？」弹层
      </Button>
      <AllLibraryDialog
        open={open}
        onOpenChange={setOpen}
        view={props.view}
        onUpload={async () => undefined}
        onResend={async () => undefined}
        siteUrl="https://www.example.org/"
        orderUrl="/order?from=tuku_unlock_done"
      />
    </div>
  );
}
