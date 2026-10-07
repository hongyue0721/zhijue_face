import { Icon } from "../common/icons";
import { StepProgress } from "./StepProgress";

export function AppHeader({
  currentStep,
  packsActive,
  onOpenPacks,
}: {
  currentStep: 1 | 2 | 3 | 4 | null;
  packsActive: boolean;
  onOpenPacks: () => void;
}) {
  return (
    <header className="app-header">
      <div className="header-inner">
        <div className="brand" aria-label="职觉 AI 面试陪练">
          <span className="brand-mark" aria-hidden="true">职</span>
          <span className="brand-text">
            <strong>职觉 <span className="brand-latin">ZhiJue</span></strong>
            <small>AI 面试陪练</small>
          </span>
        </div>
        <div className="header-steps">
          {currentStep ? <StepProgress current={currentStep} /> : null}
        </div>
        {/* 岗位知识入口独立于主流程；不占用步骤编号，也不伪造流程进度。 */}
        <button
          type="button"
          className="header-packs-link"
          aria-current={packsActive ? "page" : undefined}
          onClick={onOpenPacks}
        >
          <Icon name="book" />
          岗位知识
        </button>
      </div>
    </header>
  );
}
