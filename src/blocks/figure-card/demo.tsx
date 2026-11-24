import { FigureGrid, FigureGridSkeleton, type FigureGridProps } from "./FigureCard";

export type FigureGridDemoProps = FigureGridProps & { loading?: boolean };

/** 陈列页用：一组卡片，或加载中的样子 */
export function FigureGridDemo(props: FigureGridDemoProps) {
  return <div className="p-4">{props.loading ? <FigureGridSkeleton /> : <FigureGrid {...props} />}</div>;
}
