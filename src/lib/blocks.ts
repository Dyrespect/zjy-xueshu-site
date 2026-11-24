import type { ComponentType } from "react";

/**
 * 区块陈列的约定：每个区块文件夹里的 example.ts 默认导出 defineBlockDemo({...})，
 * /dev/blocks 会自动把它摆出来（不用改 DevBlocks.tsx）。
 */
export interface BlockExample<P> {
  /** 这组示例叫什么，如「默认」「没有结果」「加载中」 */
  name: string;
  props: P;
}

export interface BlockDemo<P extends object> {
  /** 区块名，跟文件夹名一致，如 site-header */
  block: string;
  /** 中文名，如「站点页头」 */
  title: string;
  component: ComponentType<P>;
  examples: BlockExample<P>[];
  /** 陈列页里的先后（小的在前，默认 100；同序号按区块名排） */
  order?: number;
}

export function defineBlockDemo<P extends object>(demo: BlockDemo<P>): BlockDemo<P> {
  return demo;
}
