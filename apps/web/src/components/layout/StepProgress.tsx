import { Icon } from "../common/icons";

const STEPS = ["资料", "准备", "面试", "复盘"];

export function StepProgress({ current }: { current: 1 | 2 | 3 | 4 }) {
  return (
    <ol className="step-progress" aria-label="面试准备进度">
      {STEPS.map((label, index) => {
        const number = index + 1;
        const complete = number < current;
        const active = number === current;
        return (
          <li key={label} aria-current={active ? "step" : undefined} className={complete ? "complete" : active ? "active" : undefined}>
            <span className="step-marker" aria-hidden="true">
              {complete ? <Icon name="check" strokeWidth={2.4} /> : number}
            </span>
            <span className="step-label">{label}</span>
            {complete ? <span className="visually-hidden">（已完成）</span> : null}
          </li>
        );
      })}
    </ol>
  );
}
