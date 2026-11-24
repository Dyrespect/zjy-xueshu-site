/** 「草稿，待法务或财务确认」提示（协议三页和联系我们页用）。单独一个文件：联系我们页只要它，不带上 Markdown 渲染。 */
export function DraftNotice({ open }: { open: string[] }) {
  return (
    <div role="note" className="mt-6 max-w-2xl rounded-md border px-4 py-3 text-sm leading-relaxed text-body">
      <p className="font-medium text-foreground">草稿，待法务或财务确认</p>
      <p className="mt-1">这一版是我们先写的，还没有请律师和财务看过，正式版可能会改。</p>
      {open.length ? (
        <>
          <p className="mt-2">还没定的几处：</p>
          <ul className="mt-1 flex flex-col gap-1 pl-5 [list-style:disc] marker:text-faint">
            {open.map((x, i) => (
              <li key={i}>{x}</li>
            ))}
          </ul>
        </>
      ) : null}
    </div>
  );
}
