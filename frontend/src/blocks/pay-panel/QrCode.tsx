/** 按后端给的模块矩阵（一行一个 "0101…" 字符串）画二维码。颜色跟着字色走（text-foreground），四周留 4 格白边。 */
export function QrCode({ rows, size = 208, label }: { rows: string[]; size?: number; label: string }) {
  const n = rows.length;
  if (!n) return null;
  const q = 4;
  const rects: string[] = [];
  rows.forEach((row, y) => {
    let x = 0;
    while (x < n) {
      if (row[x] === "1") {
        let w = 1;
        while (x + w < n && row[x + w] === "1") w += 1;
        rects.push(`M${x + q} ${y + q}h${w}v1h-${w}z`);
        x += w;
      } else {
        x += 1;
      }
    }
  });
  return (
    <svg
      role="img"
      aria-label={label}
      width={size}
      height={size}
      viewBox={`0 0 ${n + 2 * q} ${n + 2 * q}`}
      shapeRendering="crispEdges"
      className="bg-background text-foreground"
    >
      <path d={rects.join("")} fill="currentColor" />
    </svg>
  );
}
