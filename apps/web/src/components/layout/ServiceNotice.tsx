import { Alert, Button } from "../common/ui";

export type ServiceState =
  | { status: "checking" }
  | { status: "ready"; runMode: string; dataMode: string; contentGeneration: "configured" | "absent" }
  | { status: "unavailable" };

export function ServiceNotice({ state, onRetry }: { state: ServiceState; onRetry: () => void }) {
  if (state.status === "checking") return null;
  if (state.status === "unavailable") {
    return (
      <div className="global-notice">
        <Alert type="danger" title="服务暂未就绪">
          <p>暂时只能查看已有内容，提交已暂停。系统不会拿预录的结果冒充实时处理。</p>
          <Button size="small" type="secondary" onClick={onRetry}>
            重新检查服务
          </Button>
        </Alert>
      </div>
    );
  }
  return null;
}
