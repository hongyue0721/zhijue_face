import { useEffect, useRef } from "react";

/** Animation follows real request state; it never invents progress or a deadline. */
export function ResumeScan({ label = "正在识别简历" }: { label?: string }) {
  const ringRef = useRef<HTMLSpanElement>(null);
  const scanRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const motion = window.matchMedia("(prefers-reduced-motion: reduce)");
    let animations: Animation[] = [];
    const update = () => {
      animations.forEach((animation) => animation.cancel());
      animations = [];
      if (motion.matches) return;
      const ring = ringRef.current?.animate(
        [{ transform: "rotate(0deg)" }, { transform: "rotate(360deg)" }],
        { duration: 1800, iterations: Infinity },
      );
      const scan = scanRef.current?.animate(
        [{ transform: "translateY(-20px)" }, { transform: "translateY(20px)" }],
        { duration: 1400, iterations: Infinity, direction: "alternate", easing: "ease-in-out" },
      );
      animations = [ring, scan].filter((animation): animation is Animation => Boolean(animation));
    };
    update();
    motion.addEventListener("change", update);
    return () => {
      motion.removeEventListener("change", update);
      animations.forEach((animation) => animation.cancel());
    };
  }, []);

  return (
    <section className="resume-scan" role="status" aria-live="polite">
      <div className="resume-scan-graphic" aria-hidden="true">
        <span ref={ringRef} className="resume-scan-ring" />
        <svg viewBox="0 0 48 56" fill="none"><path d="M9 2h21l11 11v40H9zM30 2v12h11M17 25h16M17 33h16M17 41h10" /></svg>
        <span ref={scanRef} className="resume-scan-line" />
      </div>
      <h1>{label}</h1>
    </section>
  );
}
