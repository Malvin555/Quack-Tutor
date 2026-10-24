import { $, $$ } from "@scripts/lib/dom";

export function initCopy() {
  for (const btn of $$("[data-copy]")) {
    btn.addEventListener("click", async () => {
      const text = $("code", btn.parentElement!)?.dataset.copyText ?? "";
      try {
        await navigator.clipboard.writeText(text);
        btn.textContent = "copied";
      } catch {
        btn.textContent = "select + copy";
      }
      setTimeout(() => (btn.textContent = "copy"), 1600);
    });
  }
}
