import type { ReactNode } from "react";
import { Icon } from "../common/icons";

/** 页面顶部的返回导航行：左侧返回链接，右侧可放本页的辅助动作。 */
export function PageNav({
  label,
  children,
  actions,
  className = "",
}: {
  label: string;
  children?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <nav className={`page-nav ${className}`.trim()} aria-label={label}>
      <div className="page-nav__links">{children}</div>
      {actions ? <div className="page-nav__actions">{actions}</div> : null}
    </nav>
  );
}

export function BackLink({
  children,
  disabled = false,
  onClick,
}: {
  children: ReactNode;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" className="back-link" disabled={disabled} onClick={onClick}>
      <Icon name="arrow-left" />
      {children}
    </button>
  );
}

/** 页面主标题区：标题、说明与右侧主动作。 */
export function PageHeading({
  eyebrow,
  title,
  children,
  aside,
  className = "",
}: {
  eyebrow?: ReactNode;
  title: ReactNode;
  children?: ReactNode;
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <header className={`page-heading ${className}`.trim()}>
      <div className="page-heading__main">
        {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
        <h1>{title}</h1>
        {children}
      </div>
      {aside ? <div className="page-heading__aside">{aside}</div> : null}
    </header>
  );
}
