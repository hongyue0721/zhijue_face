import {
  Alert as AnyAlert,
  Button as AnyButton,
  type AnyUIReactProps,
} from "@any-design/anyui/react";
import { forwardRef, type ReactNode } from "react";
import { Icon, spinnerIconData, type IconName } from "./icons";

/*
 * AnyUI 的 Button 加载态与 Alert 图标默认使用 Iconify 名称字符串，运行时会
 * 请求 api.iconify.design。应用统一经由这里使用两者，图标全部本地渲染。
 */

type ButtonProps = Omit<AnyUIReactProps, "ref"> & { children?: ReactNode };

export const Button = forwardRef<HTMLDivElement, ButtonProps>(function Button(props, ref) {
  return <AnyButton loadingIcon={spinnerIconData} {...props} ref={ref} />;
});

type AlertType = "info" | "success" | "warn" | "danger";

const alertIcon: Record<AlertType, IconName> = {
  info: "info",
  success: "success",
  warn: "warn",
  danger: "danger",
};

type AlertProps = Omit<AnyUIReactProps, "ref"> & {
  type?: AlertType;
  title?: string;
  children?: ReactNode;
};

export const Alert = forwardRef<HTMLDivElement, AlertProps>(function Alert({ type, ...props }, ref) {
  const kind: AlertType = type ?? "info";
  return <AnyAlert type={kind} icon={<Icon name={alertIcon[kind]} />} {...props} ref={ref} />;
});
