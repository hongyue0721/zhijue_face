import { StepProgress } from "./StepProgress";

export function AppHeader({ currentStep }: { currentStep: 1 | 2 | 3 }) {
  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="brand" aria-label="职觉 AI 面试陪练">
          <span className="brand-mark" aria-hidden="true">知</span>
          <span>
            <strong>职觉</strong>
            <small>AI 面试陪练</small>
          </span>
        </div>
        <StepProgress current={currentStep} />
      </div>
    </header>
  );
}
