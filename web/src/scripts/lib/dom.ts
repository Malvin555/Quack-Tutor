export const $ = <T extends HTMLElement = HTMLElement>(
  s: string,
  r: ParentNode = document,
) => r.querySelector<T>(s);

export const $$ = <T extends HTMLElement = HTMLElement>(
  s: string,
  r: ParentNode = document,
) => Array.from(r.querySelectorAll<T>(s));

export const clamp = (n: number, a: number, b: number) =>
  Math.min(b, Math.max(a, n));

export const raf = (fn: () => void) => {
  let queued = false;
  return () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      fn();
    });
  };
};
