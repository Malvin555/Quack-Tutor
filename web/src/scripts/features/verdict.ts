import { $, $$ } from "@scripts/lib/dom";

const ALLOWED = ["TASKS.md", "QUACK_HISTORY.md"];

export function initVerdict() {
  const out = $("#verdict-out");
  const duck = $("#deny-duck");
  if (!out) return;

  const run = (raw: string) => {
    const norm = raw
      .trim()
      .replace(/\\/g, "/")
      .replace(/\/+/g, "/")
      .replace(/^\.\//, "");
    if (!norm) return;
    const parts = norm.split("/");
    const name = parts[parts.length - 1];
    const ok = ALLOWED.includes(name) || parts.includes(".quack");
    out.replaceChildren();
    const a = document.createElement("div");
    a.className = "dim";
    a.textContent = `>>> assert_writable(Path("${norm}"))`;
    const b = document.createElement("div");
    b.className = ok ? "ok" : "crit";
    b.textContent = ok
      ? "ok. This path is on the allowlist."
      : `SafetyError: Quack refuses to write ${norm}: only TASKS.md, QUACK_HISTORY.md and .quack/ are writable.`;
    out.append(a, b);
    if (duck) {
      duck.dataset.mood = "";
      void duck.offsetWidth;
      duck.dataset.mood = ok ? "happy" : "no";
    }
  };

  const btns = $$<HTMLButtonElement>("#files button");
  for (const b of btns) {
    b.addEventListener("click", () => {
      btns.forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      run(b.dataset.path!);
    });
  }
  $("#try")?.addEventListener("submit", (e) => {
    e.preventDefault();
    btns.forEach((x) => x.setAttribute("aria-pressed", "false"));
    run(($("#path") as HTMLInputElement).value);
  });
}
