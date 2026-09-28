import { StepProgress } from "./StepProgress";

export function AppHeader({
  currentStep,
  onOpenPacks,
}: {
  currentStep: 1 | 2 | 3 | 4 | null;
  onOpenPacks: () => void;
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
          {/* 岗位知识入口独立于五步主流程；不占用步骤编号。 */}
          <button type="button" className="header-packs-link" onClick={onOpenPacks}>
            岗位知识
          </button>
          {currentStep ? <StepProgress current={currentStep} /> : null}
        </div>
      </div>
    </header>
  );
}
