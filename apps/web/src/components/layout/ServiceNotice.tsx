import { Alert, Button } from "@any-design/anyui/react";

export type ServiceState =
  | { status: "checking" }
  | { status: "ready"; runMode: string; dataMode: string }
  | { status: "unavailable" };

export function ServiceNotice({ state, onRetry }: { state: ServiceState; onRetry: () => void }) {
  if (state.status === "checking") return null;
  if (state.status === "unavailable") {
    return (
      <div className="global-notice">
        <Alert type="danger" title="服务暂未就绪">
          <p>现在只能查看已有内容，提交操作已暂停；系统不会用预先录制的成功结果代替真实处理。</p>
          <Button size="small" type="secondary" onClick={onRetry}>
            重新检查服务
          </Button>
        </Alert>
      </div>
    );
  }
  return null;
}
