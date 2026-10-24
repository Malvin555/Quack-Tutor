import { $ } from "@scripts/lib/dom";

const D: Record<string, { lines: number; tokens: string; max: number }> = {
  "1": { lines: 30, tokens: "~1,000–1,500", max: 1500 },
  "2": { lines: 80, tokens: "~2,000–3,000", max: 3000 },
  "3": { lines: 150, tokens: "~4,000–5,000", max: 5000 },
};

export function initDepth() {
  const range = $("#depth") as HTMLInputElement | null;
  if (!range) return;

  const strip = $("#strip")!;
  const tok = $("#tok")!;
  const linesOut = $("#lines-out")!;
  const tokOut = $("#tok-out")!;
  const depthOut = $("#depth-out")!;

  const upd = () => {
    const d = D[range.value];
    strip.style.setProperty("--win", String((d.lines / 400) * 100));
    tok.style.setProperty("--tok", String((d.max / 5000) * 100));
    linesOut.textContent = `${d.lines} lines`;
    tokOut.textContent = d.tokens;
    depthOut.textContent = range.value;
    range.setAttribute(
      "aria-valuetext",
      `depth ${range.value}: ${d.lines} lines, ${d.tokens} tokens`,
    );
  };
  range.addEventListener("input", upd);
  upd();
}
