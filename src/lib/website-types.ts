/** 官网设置（/api/website/config、/api/admin/website/*）。跟后端 app/website/config.py 对上。 */

export interface SiteConfig {
  company_name: string;
  credit_code: string;
  icp: string;
  icp_url: string;
  /** 公安联网备案号；空 = 还没备案，页脚不显示 */
  police_beian: string;
  police_beian_url: string;
  phone: string;
  /** 「微信同号」 */
  phone_note: string;
  email: string;
  address: string;
  service_hours: string;
  /** 投诉多久答复 */
  reply_promise: string;
  /** 公开给搜索引擎：关 = 页面带 noindex、robots.txt 全站不让爬 */
  indexable: boolean;
  maintenance: boolean;
  maintenance_text: string;
  /** 小红书、闲鱼店铺链接（自有网页暂不收款时下单页给的去处）；空 = 只显示文字 */
  xhs_shop_url?: string;
  xianyu_shop_url?: string;
  /** 两个平台怎么找到店（比如「搜：心理学汇报 PPT 定制」）；空 = 不显示 */
  platform_shop_note?: string;
  /** 营业执照公示页 /license 的文字（类型、法定代表人、住所、成立日期、登记机关） */
  license_type?: string;
  legal_rep?: string;
  reg_address?: string;
  established?: string;
  registry_authority?: string;
}

export type WebsiteConfigFull = Omit<SiteConfig, "icp_url" | "police_beian_url">;

export interface WebsiteSettingsData {
  config: WebsiteConfigFull;
  /** 正式开放前要补的项 → 说明 */
  launch_fields: Record<string, string>;
  pending_launch: string[];
}

export interface ConsentRow {
  at: string;
  checkout: string;
  items: string[];
  terms_version: string;
  privacy_version: string;
  ip: string;
}

/** 下单页付款前要勾的三项（和后端 app/website/consent.py 的 REQUIRED_CONSENTS 一一对上） */
export type ConsentKey = "terms_privacy" | "ai_processing" | "custom_no_refund";
export const CONSENT_KEYS: ConsentKey[] = ["terms_privacy", "ai_processing", "custom_no_refund"];
