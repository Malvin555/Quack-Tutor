import { $, clamp } from "@scripts/lib/dom";
import { reduce } from "@scripts/lib/motion";

export function initWalker() {
  const walker = $(".walker");
  const rail = $(".rail-in");
  const trail = $(".trail");
  if (!walker || !rail || !trail) return;
  if (getComputedStyle(rail.parentElement!).display === "none") return;

  let target = 0;
  let cur = 0;
  let running = false;

  const measure = () => {
    const max = document.documentElement.scrollHeight - innerHeight;
    target = max > 0 ? clamp(scrollY / max, 0, 1) : 0;
  };

  const step = () => {
    cur += (target - cur) * (reduce ? 1 : 0.05);
    if (Math.abs(target - cur) < 0.0003) cur = target;
    const y = 14 + cur * Math.max(0, rail.clientHeight - 90);
    walker.style.transform = `translate(-50%, ${y}px)`;
    trail.style.height = `${y + 58}px`;
    walker.dataset.mood = Math.abs(target - cur) > 0.012 ? "think" : "idle";
    if (cur !== target) requestAnimationFrame(step);
    else running = false;
  };

  const kick = () => {
    measure();
    if (!running) {
      running = true;
      requestAnimationFrame(step);
    }
  };

  addEventListener("scroll", kick, { passive: true });
  addEventListener("resize", kick);
  kick();
}
