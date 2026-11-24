import { useState } from "react";

import { RequestForm } from "@/blocks/request-dialog";
import { sendRequest } from "@/blocks/request-dialog/load";
import { SiteLink } from "@/components/site-link";

import { useTitle } from "./gallery-context";

/** /request 提需求：找不到想画的图，告诉我们（页头导航的「提需求」，表单和弹层是同一个）。 */
export default function RequestPage() {
  useTitle("提需求");
  const [done, setDone] = useState("");
  return (
    <main className="mx-auto max-w-2xl px-4 pt-8 pb-16 sm:px-6 sm:pt-12">
      <h1 className="text-2xl font-semibold">告诉我们你要画什么</h1>
      <p className="mt-2 text-[15px] text-body">我们照着去补图，补上以后搜同样的话就能找到。</p>
      <div className="mt-8">
        {done ? (
          <div className="flex flex-col gap-3">
            <p className="text-[15px] text-foreground">{done}</p>
            <SiteLink href="/" className="text-primary hover:text-primary-hover">
              回去找图
            </SiteLink>
          </div>
        ) : (
          <RequestForm onSubmit={sendRequest} onDone={setDone} />
        )}
      </div>
    </main>
  );
}
