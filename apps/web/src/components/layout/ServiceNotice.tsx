import { Alert } from "@any-design/anyui/react";

export type ServiceState =
  | { status: "checking" }
  | { status: "ready"; runMode: string; dataMode: string }
  | { status: "unavailable" };

export function ServiceNotice({ state }: { state: ServiceState }) {
  if (state.status === "checking") return null;
  if (state.status === "unavailable") {
    return (
      <div className="global-notice">
        <Alert type="danger" title="服务依赖未就绪">
          当前只能查看已有状态，提交操作已停用；系统不会自动切换到预录成功结果。
        </Alert>
      </div>
    );
  }
  if (state.runMode === "fixture" || state.runMode === "replay") {
    return (
      <div className="global-notice">
        <Alert type="info" title={`测试运行模式：${state.runMode}`}>
          当前分析结果用于本地流程验证，不代表真实模型效果。
        </Alert>
      </div>
    );
  }
  return null;
}
