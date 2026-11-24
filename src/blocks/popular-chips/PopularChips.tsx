import { Link } from "react-router";

import type { Chip } from "@/lib/figures-types";
import { cn } from "@/lib/utils";

export interface PopularChipsProps {
  label?: string;
  chips: Chip[];
  hrefFor: (chip: Chip) => string;
  className?: string;
}

/** 首页搜索框下面那排「常见要画的」：点一下就搜 */
export function PopularChips({ label = "常见要画的", chips, hrefFor, className }: PopularChipsProps) {
  if (!chips.length) return null;
  return (
    <div className={cn("flex flex-wrap items-center gap-x-2 gap-y-2.5", className)}>
      <span className="mr-1 text-sm text-muted-foreground">{label}</span>
      {chips.map((c) => (
        <Link
          key={c.label}
          to={hrefFor(c)}
          className="rounded-full border px-3 py-1 text-sm text-body transition-colors hover:border-ring/50 hover:text-foreground"
        >
          {c.label}
        </Link>
      ))}
    </div>
  );
}
