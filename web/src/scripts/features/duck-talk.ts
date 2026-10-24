import { $, $$ } from "@scripts/lib/dom";

const TIPS = [
  "I never edit your files. Not even if you ask nicely.",
  "Indexing costs 0 tokens. I counted.",
  'Pipe the traceback: pytest -x 2>&1 | quack ask "why?" --stdin',
  "Ask the same question twice. The second answer is free.",
  "One question at a time. I'm a duck.",
  "quack verify proves I kept my wings to myself.",
];

export function initDuckTalk() {
  let i = Math.floor(Math.random() * TIPS.length);
  for (const d of $$(".duck[data-talk]")) {
    const b = $(".bubble", d);
    if (!b) continue;
    let timer = 0;
    d.tabIndex = 0;
    d.setAttribute("role", "button");
    d.setAttribute("aria-label", "Quack the duck. Activate for a tip.");
    const say = () => {
      b.textContent = TIPS[i++ % TIPS.length];
      b.hidden = false;
      const prev = d.dataset.mood;
      d.dataset.mood = "happy";
      clearTimeout(timer);
      timer = window.setTimeout(() => {
        b.hidden = true;
        d.dataset.mood = prev === "happy" ? "idle" : prev;
      }, 4200);
    };
    d.addEventListener("click", say);
    d.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        say();
      }
    });
  }
}
