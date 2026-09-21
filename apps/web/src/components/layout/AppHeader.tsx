import { StepProgress } from "./StepProgress";

export function AppHeader({
  currentStep,
  mode,
}: {
  currentStep: 1 | 2 | 3 | 4 | null;
  mode?: string;
}) {
  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="brand" aria-label="职觉 AI 面试陪练">
          <span className="brand-mark" aria-hidden="true">职</span>
          <span>
            <strong>职觉 <span className="brand-latin">ZhiJue</span></strong>
            <small>AI 面试陪练</small>
          </span>
        </div>
        <div className="header-right">
          {/* live/fixture/replay 与 synthetic 数据模式必须对用户明示（工程规范第 2 条）。 */}
          {mode ? <span className="runtime-mode-chip">{mode}</span> : null}
          {currentStep ? <StepProgress current={currentStep} /> : <span className="header-context">简历整理</span>}
        </div>
      </div>
    </header>
  );
}
