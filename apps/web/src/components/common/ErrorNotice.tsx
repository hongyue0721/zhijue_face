import { Alert, Button } from "./ui";
import { ApiError } from "../../api";

function guidance(error: unknown): string {
  if (error instanceof TypeError) return "无法连接本地服务，请确认服务正在运行后重试。";
  if (!(error instanceof ApiError)) return "页面暂时无法完成当前操作，请刷新最新状态后重试。";
  switch (error.code) {
    case "SERVICE_NOT_READY":
      return "服务还没准备好，请稍后重新检查服务再提交。";
    case "CAPACITY_LIMITED":
      return "当前排队的任务较多，请稍等片刻在本页重试。";
    case "REVISION_CONFLICT":
      return "页面内容已经更新，请先读取最新状态再提交。";
    case "PROFILE_UNCONFIRMED":
      return "请先在资料页核对并确认至少一条经历。";
    case "RESOURCE_NOT_FOUND":
      return "这项内容不存在、已被删除，或当前页面无权读取。请返回上一步重新进入。";
    default:
      return error.message;
  }
}

function errorTitle(error: unknown): string {
  if (error instanceof TypeError) return "无法连接服务";
  if (!(error instanceof ApiError)) return "页面处理未完成";
  const titles: Record<string, string> = {
    SERVICE_NOT_READY: "服务暂未就绪",
    CAPACITY_LIMITED: "当前排队较多",
    REVISION_CONFLICT: "页面状态已更新",
    PROFILE_UNCONFIRMED: "经历资料尚未确认",
    RESOURCE_NOT_FOUND: "内容未找到",
  };
  return titles[error.code] ?? "操作未完成";
}

export function ErrorNotice({ error, onReload }: { error: unknown; onReload?: () => void }) {
  if (!error) return null;
  return (
    <Alert type="danger" title={errorTitle(error)}>
      <p>{guidance(error)}</p>
      {error instanceof ApiError ? (
        <details className="compact-details">
          <summary>查看错误编号</summary>
          <code>{error.code}</code>
        </details>
      ) : null}
      {onReload ? (
        <Button size="small" type="secondary" onClick={onReload}>
          重新读取最新状态
        </Button>
      ) : null}
    </Alert>
  );
}
