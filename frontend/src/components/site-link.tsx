import type { AnchorHTMLAttributes } from "react";
import { Link } from "react-router";

export interface SiteLinkProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  href: string;
}

/** 本前端里的页面（/ 开头、不是 .html）走前端路由；官网的 .html 和别的域名整页跳转，同一个窗口打开。 */
export function isSpaHref(href: string): boolean {
  return href.startsWith("/") && !href.startsWith("//") && !/\.html(?:[?#]|$)/.test(href);
}

export function SiteLink({ href, children, ...rest }: SiteLinkProps) {
  if (isSpaHref(href)) {
    return (
      <Link to={href} {...rest}>
        {children}
      </Link>
    );
  }
  return (
    <a href={href} {...rest}>
      {children}
    </a>
  );
}
