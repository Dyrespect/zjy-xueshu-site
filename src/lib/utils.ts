import { type ClassValue, clsx } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

// tokens.css 里自己加的字号（text-display / text-headline / text-lead，官网 v2）要告诉 tailwind-merge 是字号，
// 不然它当成文字颜色，和 text-foreground 这类放一起时会把字号删掉
const twMerge = extendTailwindMerge({
  extend: { classGroups: { "font-size": [{ text: ["display", "headline", "lead"] }] } },
});

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
