import { useState } from "react";

import { SubmitForm } from "@/blocks/submit-dialog";
import { sendSubmission } from "@/blocks/submit-dialog/load";
import { SiteLink } from "@/components/site-link";

import { useTitle } from "./gallery-context";

/** /submit 投图：推荐一张好图，审过收进图库，详情页写上署名（页头导航的「投图」）。 */
export default function SubmitPage() {
  useTitle("投图");
  const [done, setDone] = useState("");
  return (
    <main className="mx-auto max-w-2xl px-4 pt-8 pb-16 sm:px-6 sm:pt-12">
      <h1 className="text-2xl font-semibold">投一张你觉得画得好的图</h1>
      <p className="mt-2 text-[15px] text-body">我们审核后收进下一版图库，详情页和图库包的贡献者名单里写上你的署名。</p>
      <div className="mt-8">
        {done ? (
          <div className="flex flex-col gap-3">
            <p className="text-[15px] text-foreground">{done}</p>
            <SiteLink href="/" className="text-primary hover:text-primary-hover">
              回去找图
            </SiteLink>
          </div>
        ) : (
          <SubmitForm onSubmit={sendSubmission} onDone={setDone} />
        )}
      </div>
    </main>
  );
}
