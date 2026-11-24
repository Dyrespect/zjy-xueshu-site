import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface FigureSearchBoxProps {
  defaultValue?: string;
  /** 占位字：一句真实的问法 */
  placeholder?: string;
  /** 手机上框窄，换一句短的（不然显示半句） */
  shortPlaceholder?: string;
  /** hero = 首页第一屏的大框；compact = 结果页顶上 */
  size?: "hero" | "compact";
  autoFocus?: boolean;
  onSubmit: (query: string) => void;
}

function useNarrow() {
  const query = "(max-width: 639px)";
  const [narrow, setNarrow] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  useEffect(() => {
    const m = window.matchMedia(query);
    const on = () => setNarrow(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return narrow;
}

export function FigureSearchBox({
  defaultValue = "",
  placeholder = "我做的是手机依赖和睡眠的问卷研究，想画假设模型",
  shortPlaceholder = "被试内实验的试次流程怎么画",
  size = "hero",
  autoFocus,
  onSubmit,
}: FigureSearchBoxProps) {
  const [value, setValue] = useState(defaultValue);
  useEffect(() => setValue(defaultValue), [defaultValue]);
  const hero = size === "hero";
  const narrow = useNarrow();

  function submit(e: FormEvent) {
    e.preventDefault();
    const q = value.trim();
    if (q) onSubmit(q);
  }

  return (
    <form role="search" onSubmit={submit} className="w-full">
      <div
        className={cn(
          "flex items-center gap-2 rounded-xl border bg-background transition-[border-color,box-shadow] focus-within:border-ring focus-within:ring-[3px] focus-within:ring-ring/15",
          hero ? "h-14 pr-2 pl-5 sm:h-16" : "h-11 pr-1.5 pl-4",
        )}
      >
        <input
          type="search"
          name="q"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={narrow ? shortPlaceholder : placeholder}
          autoFocus={autoFocus}
          maxLength={200}
          enterKeyHint="search"
          aria-label="描述你要画的图"
          className={cn(
            "min-w-0 flex-1 bg-transparent text-foreground outline-none placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:hidden",
            hero ? "text-base sm:text-[17px]" : "text-[15px]",
          )}
        />
        <Button type="submit" size={hero ? "lg" : "sm"} className={hero ? "h-10 px-5 sm:h-11 sm:px-6" : "px-4"}>
          找图
        </Button>
      </div>
    </form>
  );
}
