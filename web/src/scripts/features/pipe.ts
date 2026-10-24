import { $, $$, clamp, raf } from "@scripts/lib/dom";
import { reduce } from "@scripts/lib/motion";

export function initPipe() {
  const pipe = $("#pipe");
  if (!pipe) return;

  const steps = $$(".step", pipe);
  const upd = () => {
    const line = innerHeight * 0.62;
    const r = pipe.getBoundingClientRect();
    let last = -1;
    steps.forEach((s, i) => {
      const on = reduce || s.getBoundingClientRect().top < line;
      s.classList.toggle("on", on);
      if (on) last = i;
    });
    const p = reduce
      ? 1
      : last < 0
        ? 0
        : clamp((line - r.top) / r.height, 0, 1);
    pipe.style.setProperty("--p", String(p));
  };
  const go = raf(upd);
  addEventListener("scroll", go, { passive: true });
  addEventListener("resize", go);
  upd();
}
