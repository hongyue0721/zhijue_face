const STEPS = ["导入资料", "准备面试", "模拟面试"];

export function StepProgress({ current }: { current: 1 | 2 | 3 }) {
  return (
    <ol className="step-progress" aria-label="面试准备进度">
      {STEPS.map((label, index) => {
        const number = index + 1;
        const complete = number < current;
        const active = number === current;
        return (
          <li key={label} className={complete ? "complete" : active ? "active" : undefined}>
            <span className="step-marker" aria-hidden="true">
              {complete ? "✓" : number}
            </span>
            <span>{label}</span>
          </li>
        );
      })}
    </ol>
  );
}
