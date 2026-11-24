import { useState } from "react";

import { LicenseView } from "@/blocks/business-license";
import { useSiteConfig } from "@/blocks/site-shell/load";

/**
 * /license 营业执照公示（《电子商务法》第十五条；12 号设计第十一节）：文字从后台「官网」设置读（执照变更后在那里改），
 * 图片是 scripts/site_assets.py 从营业执照电子版转的 site-assets/license.webp（图不进 git）。
 */
export function LicensePage() {
  const site = useSiteConfig();
  const [missing, setMissing] = useState(false);
  return <LicenseView info={site} imageMissing={missing} onImageError={() => setMissing(true)} />;
}
