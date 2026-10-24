import { $$, raf } from "@scripts/lib/dom";

export function initDuckPupils() {
  const pupils = $$<HTMLElement>(".duck .pupil");
  if (pupils.length === 0) return;

  const last = { x: 0, y: 0 };
  const move = raf(() => {
    for (const p of pupils) {
      const svg = (p as unknown as SVGElement).ownerSVGElement;
      if (!svg) continue;
      const r = svg.getBoundingClientRect();
      if (r.bottom < 0 || r.top > innerHeight) continue;
      const dx = last.x - (r.left + r.width * 0.68);
      const dy = last.y - (r.top + r.height * 0.28);
      const d = Math.hypot(dx, dy) || 1;
      const k = Math.min(2.2, d / 70);
      p.style.transform = `translate(${(dx / d) * k}px, ${(dy / d) * k}px)`;
    }
  });

  addEventListener(
    "pointermove",
    (e) => {
      last.x = e.clientX;
      last.y = e.clientY;
      move();
    },
    { passive: true },
  );
}
