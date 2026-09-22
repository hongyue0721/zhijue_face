import { StepProgress } from "./StepProgress";

export function AppHeader({
  currentStep,
}: {
  currentStep: 1 | 2 | 3 | 4 | null;
}) {
  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="brand" aria-label="职觉 AI 面试陪练">
          <span className="brand-mark" aria-hidden="true">职</span>
          <span>
            <strong>职觉 <span className="brand-latin">ZhiJue</span></strong>

          </span>
        </div>
        <div className="header-right">
          {currentStep ? <StepProgress current={currentStep} /> : null}
        </div>
      </div>
    </header>
  );
}
