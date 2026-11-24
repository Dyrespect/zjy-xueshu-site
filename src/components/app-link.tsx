import type { AnchorHTMLAttributes } from "react";
import { Link } from "react-router";

export interface AppLinkProps extends AnchorHTMLAttributes<HTMLAnchorElement> {
  href: string;
}

/** 站内地址（/ 开头）走前端路由，不整页刷新；站外地址新窗口打开。 */
export function AppLink({ href, children, ...rest }: AppLinkProps) {
  if (href.startsWith("/") && !href.startsWith("//")) {
    return (
      <Link to={href} {...rest}>
        {children}
      </Link>
    );
  }
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" {...rest}>
      {children}
    </a>
  );
}
