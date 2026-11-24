export interface LicenseInfo {
  company_name: string;
  credit_code: string;
  license_type?: string;
  legal_rep?: string;
  reg_address?: string;
  established?: string;
  registry_authority?: string;
}

export interface LicenseViewProps {
  info: LicenseInfo | null;
  /** 执照电子版图片（/site-assets/license.webp）；没放图时显示文字说明 */
  imageSrc?: string;
  /** 图片加载失败（没跑 scripts/site_assets.py） */
  imageMissing?: boolean;
  onImageError?: () => void;
}

/** 营业执照公示（《电子商务法》第十五条）：执照图片 + 文字信息。只吃 props。 */
export function LicenseView({ info, imageSrc = "/site-assets/license.webp", imageMissing, onImageError }: LicenseViewProps) {
  const rows: [string, string | undefined][] = info
    ? [["名称", info.company_name], ["统一社会信用代码", info.credit_code], ["类型", info.license_type], ["法定代表人", info.legal_rep],
       ["住所", info.reg_address], ["成立日期", info.established], ["登记机关", info.registry_authority]]
    : [];
  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-8 px-4 py-10 sm:px-6">
      <div className="flex flex-col gap-2">
        <h1 className="font-display text-3xl leading-tight font-bold tracking-wide text-foreground">营业执照</h1>
        <p className="text-[15px] leading-relaxed text-body">
          按《中华人民共和国电子商务法》第十五条公示。执照信息以国家企业信用信息公示系统为准，可以到
          {" "}
          <a href="https://www.gsxt.gov.cn/" target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2 hover:text-primary-hover">
            www.gsxt.gov.cn
          </a>
          {" "}
          按统一社会信用代码查询。
        </p>
      </div>
      <dl className="grid grid-cols-[7.5rem_1fr] gap-x-3 gap-y-3 rounded-lg border px-5 py-5 text-sm sm:grid-cols-[8rem_1fr] sm:gap-x-4" data-testid="license-info">
        {rows.map(([k, v]) => (
          <div key={k} className="contents">
            <dt className="text-muted-foreground">{k}</dt>
            <dd className={k === "统一社会信用代码" ? "font-mono tabular-nums text-foreground" : "text-foreground"}>{v || "—"}</dd>
          </div>
        ))}
      </dl>
      <figure className="flex flex-col gap-2">
        {imageMissing ? (
          <p className="rounded-lg border px-5 py-10 text-center text-sm text-muted-foreground">执照图片待上传，文字信息见上表。</p>
        ) : (
          <img src={imageSrc} alt="营业执照电子版" width={1600} height={1125} loading="lazy" onError={onImageError}
            className="h-auto w-full rounded-lg border" data-testid="license-image" />
        )}
        <figcaption className="text-xs leading-relaxed text-muted-foreground">营业执照电子版（仅供在本网站公示经营者信息使用）。</figcaption>
      </figure>
    </div>
  );
}
