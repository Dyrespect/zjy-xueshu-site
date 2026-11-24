import { useState } from "react";

import { TakedownForm } from "@/blocks/takedown-form";
import { sendTakedown } from "@/blocks/takedown-form/load";

import { useGallery, useTitle } from "./gallery-context";

/** /copyright 版权问题：版权方要求删除，限时内下架（页脚「版权问题」）。 */
export default function CopyrightPage() {
  useTitle("版权问题");
  const { map } = useGallery();
  const [done, setDone] = useState("");
  return (
    <main className="mx-auto max-w-2xl px-4 pt-8 pb-16 sm:px-6 sm:pt-12">
      <h1 className="text-2xl font-semibold">版权问题</h1>
      <div className="mt-6">
        {done ? <p className="text-[15px] text-foreground">{done}</p> : <TakedownForm hours={map?.takedown_hours ?? 48} onSubmit={sendTakedown} onDone={setDone} />}
      </div>
    </main>
  );
}
