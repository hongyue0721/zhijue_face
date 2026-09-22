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
  if (state.runMode === "fixture" || state.runMode === "replay") {
    // 负责人约束要求 fixture/replay 对用户明示；明示中文事实，不展示内部枚举值。
    return (
      <div className="global-notice">
        <Alert type="info" title={state.runMode === "fixture" ? "演示数据模式" : "回放数据模式"}>
          {state.runMode === "fixture"
            ? "当前分析结果由本地演示数据产生，用于流程验证，不代表真实模型效果。"
            : "当前分析结果来自预先录制的回放内容，用于流程验证，不代表真实模型效果。"}
        </Alert>
      </div>
    );
  }
  return null;
}
