import { $$ } from "@scripts/lib/dom";

export function initReveal() {
  if (!("IntersectionObserver" in window)) return;
  const io = new IntersectionObserver(
    (es) =>
      es.forEach((e) => {
        if (e.isIntersecting) {
          e.target.classList.add("in");
          io.unobserve(e.target);
        }
      }),
    { rootMargin: "0px 0px -8% 0px", threshold: 0.06 },
  );
  $$(".rv").forEach((el) => io.observe(el));
}
