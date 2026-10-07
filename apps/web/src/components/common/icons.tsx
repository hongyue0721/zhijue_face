import type { ReactElement, SVGProps } from "react";

/*
 * 本地内联图标。不使用 @iconify 字符串名称：那会在浏览器运行时向
 * api.iconify.design 请求图标数据，违背“不加载远程资源”的约定，
 * 离线演示时也会变成空白。
 */
export type IconName =
  | "arrow-left"
  | "arrow-right"
  | "check"
  | "info"
  | "warn"
  | "danger"
  | "success"
  | "document"
  | "upload"
  | "book"
  | "sparkle"
  | "close";

const paths: Record<IconName, ReactElement> = {
  "arrow-left": <path d="M15 18l-6-6 6-6M9.5 12H20" />,
  "arrow-right": <path d="M9 6l6 6-6 6M4 12h10.5" />,
  check: <path d="M5 12.5l4.2 4.2L19 7" />,
  info: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5.5M12 7.6v.4" />
    </>
  ),
  warn: (
    <>
      <path d="M12 3.8l9 15.7H3z" />
      <path d="M12 10v4.4M12 17v.3" />
    </>
  ),
  danger: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M9 9l6 6M15 9l-6 6" />
    </>
  ),
  success: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M8 12.3l2.7 2.7L16.2 9.4" />
    </>
  ),
  document: (
    <>
      <path d="M6 2.8h8.2l4 4V21.2H6z" />
      <path d="M14 2.8v4.2h4.2M9 12h6M9 15.5h6M9 19h3.5" />
    </>
  ),
  upload: <path d="M12 15.5V4.5M7.5 9L12 4.5 16.5 9M4.5 15v4.5h15V15" />,
  book: (
    <>
      <path d="M5 4.5A1.5 1.5 0 016.5 3H19v15.5H6.5A1.5 1.5 0 005 20z" />
      <path d="M5 20a1.5 1.5 0 001.5 1.5H19v-3" />
    </>
  ),
  close: <path d="M6.5 6.5l11 11M17.5 6.5l-11 11" />,
  sparkle: <path d="M12 3l1.9 5.6L19.5 10.5l-5.6 1.9L12 18l-1.9-5.6L4.5 10.5l5.6-1.9z" />,
};

export function Icon({ name, ...props }: { name: IconName } & SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className="icon"
      {...props}
    >
      {paths[name]}
    </svg>
  );
}

/** Iconify 对象形式在本地渲染，不触发网络请求；仅用于需要 IconLike 的组件属性。 */
export const spinnerIconData = {
  body: '<circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-dasharray="40 100"/>',
  width: 24,
  height: 24,
};
