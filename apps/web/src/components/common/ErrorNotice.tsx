import { Alert, Button } from "@any-design/anyui/react";
import { ApiError } from "../../api";

function guidance(error: unknown): string {
  if (!(error instanceof ApiError)) return "网络连接失败，请检查本地服务后重试。";
  switch (error.code) {
    case "SERVICE_NOT_READY":
      return "服务依赖尚未就绪，当前操作不会伪装成成功。";
    case "CAPACITY_LIMITED":
      return "当前处理队列已满，请稍后使用原页面重试。";
    case "REVISION_CONFLICT":
      return "页面数据已过期，请刷新最新状态后再提交。";
    case "PROFILE_UNCONFIRMED":
      return "请先在资料导入页确认至少一版资料快照。";
    default:
      return error.message;
  }
}

export function ErrorNotice({ error, onReload }: { error: unknown; onReload?: () => void }) {
  if (!error) return null;
  const code = error instanceof ApiError ? error.code : "NETWORK_ERROR";
  return (
    <Alert type="danger" title={`操作未完成 · ${code}`}>
      <p>{guidance(error)}</p>
      {onReload ? (
        <Button size="small" type="secondary" onClick={onReload}>
          刷新真实状态
        </Button>
      ) : null}
    </Alert>
  );
}
