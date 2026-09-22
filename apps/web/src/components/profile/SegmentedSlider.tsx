import { useRef } from "react";
import {
  decisionFromSliderTarget,
  sliderActionFromDecision,
  targetFromSliderKey,
  type SliderAction,
  type ClaimDecision,
} from "./claimDecisions";

export interface SegmentedSliderProps {
  claimId: string;
  decision: ClaimDecision | undefined;
  disabled?: boolean;
  onDecision: (decision: ClaimDecision | null) => void;
}

export function SegmentedSlider({
  claimId,
  decision,
  disabled = false,
  onDecision,
}: SegmentedSliderProps) {
  const currentAction: SliderAction = sliderActionFromDecision(decision);

  const rejectRef = useRef<HTMLButtonElement>(null);
  const acceptRef = useRef<HTMLButtonElement>(null);

  const select = (target: SliderAction, moveFocus = false) => {
    if (disabled) return;
    onDecision(decisionFromSliderTarget(claimId, target));
    if (!moveFocus) return;
    const targetRef = target === "reject" ? rejectRef : acceptRef;
    requestAnimationFrame(() => targetRef.current?.focus());
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      select(
        targetFromSliderKey(
          currentAction,
          event.key as "ArrowLeft" | "ArrowRight" | "ArrowUp" | "ArrowDown" | "Home" | "End",
        ),
        true,
      );
    }
  };

  return (
    <div
      className={`segmented-slider segmented-slider--${currentAction} ${disabled ? "segmented-slider--disabled" : ""}`}
      role="radiogroup"
      aria-label="选择事实核对结果"
      onKeyDown={handleKeyDown}
      aria-disabled={disabled}
    >
      <div className="segmented-slider-thumb" aria-hidden="true" />
      <button
        ref={acceptRef}
        type="button"
        role="radio"
        aria-checked={currentAction === "accept"}
        aria-label="采用该事实"
        disabled={disabled}
        tabIndex={currentAction !== "reject" && !disabled ? 0 : -1}
        className={`slider-option slider-option--accept ${currentAction === "accept" ? "is-selected" : ""}`}
        onClick={() => select(currentAction === "accept" ? "neutral" : "accept")}
      >采用</button>
      <button
        ref={rejectRef}
        type="button"
        role="radio"
        aria-checked={currentAction === "reject"}
        aria-label="不采用该事实"
        disabled={disabled}
        tabIndex={currentAction === "reject" && !disabled ? 0 : -1}
        className={`slider-option slider-option--reject ${currentAction === "reject" ? "is-selected" : ""}`}
        onClick={() => select(currentAction === "reject" ? "neutral" : "reject")}
      >不采用</button>
    </div>
  );
}
