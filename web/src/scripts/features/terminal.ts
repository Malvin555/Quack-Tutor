import { $, $$ } from "@scripts/lib/dom";
import { reduce } from "@scripts/lib/motion";

export function initTerminal() {
  const term = $("#term");
  const cmd = $("#cmd");
  const replay = $("#replay");
  if (!term || !cmd) return;

  const lines = $$(".ln", term);
  const full = cmd.textContent ?? "";
  let timers: number[] = [];

  const play = () => {
    timers.forEach(clearTimeout);
    timers = [];
    lines.slice(1).forEach((l) => l.classList.add("pending"));
    cmd.textContent = "";
    let t = 0;
    for (const ch of full) {
      t += 18;
      timers.push(
        window.setTimeout(() => {
          cmd.textContent += ch;
        }, t),
      );
    }
    lines.slice(1).forEach((l, i) => {
      t += l.dataset.r === lines[i]?.dataset.r ? 140 : 380;
      timers.push(window.setTimeout(() => l.classList.remove("pending"), t));
    });
  };

  if (!reduce && "IntersectionObserver" in window) {
    const io = new IntersectionObserver(
      (es) => {
        if (es[0].isIntersecting) {
          play();
          io.disconnect();
        }
      },
      { threshold: 0.35 },
    );
    io.observe(term);
    replay?.addEventListener("click", play);
  } else {
    replay?.setAttribute("hidden", "");
  }

  for (const c of $$("[data-callout]")) {
    const on = () => {
        term.dataset.hl = c.dataset.callout!;
      },
      off = () => {
        delete term.dataset.hl;
      };
    c.addEventListener("mouseenter", on);
    c.addEventListener("focus", on);
    c.addEventListener("mouseleave", off);
    c.addEventListener("blur", off);
  }
}
