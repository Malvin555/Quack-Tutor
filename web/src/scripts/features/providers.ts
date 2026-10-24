import { $ } from "@scripts/lib/dom";

type Provider = { host: string; env: string; model: string };

const P: Record<string, Provider> = {
  ollama: { host: "localhost:11434", env: "", model: "gemma3:4b" },
  lmstudio: { host: "localhost:1234", env: "", model: "local-model" },
  llamacpp: { host: "localhost:8080", env: "", model: "local-model" },
  openrouter: {
    host: "openrouter.ai",
    env: "OPENROUTER_API_KEY",
    model: "google/gemma-3-27b-it",
  },
  anthropic: {
    host: "api.anthropic.com",
    env: "ANTHROPIC_API_KEY",
    model: "claude-haiku-5-5",
  },
  openai: {
    host: "api.openai.com",
    env: "OPENAI_API_KEY",
    model: "gpt-4o-mini",
  },
  groq: {
    host: "api.groq.com",
    env: "GROQ_API_KEY",
    model: "llama-3.3-70b-versatile",
  },
  together: {
    host: "api.together.xyz",
    env: "TOGETHER_API_KEY",
    model: "Llama-3.3-70B-Instruct-Turbo",
  },
  mistral: {
    host: "api.mistral.ai",
    env: "MISTRAL_API_KEY",
    model: "mistral-small-latest",
  },
  deepseek: {
    host: "api.deepseek.com",
    env: "DEEPSEEK_API_KEY",
    model: "deepseek-chat",
  },
  gemini: {
    host: "generativelanguage.googleapis.com",
    env: "GEMINI_API_KEY",
    model: "gemini-2.0-flash",
  },
  cerebras: {
    host: "api.cerebras.ai",
    env: "CEREBRAS_API_KEY",
    model: "llama-3.3-70b",
  },
  fireworks: {
    host: "api.fireworks.ai",
    env: "FIREWORKS_API_KEY",
    model: "llama-v3p3-70b-instruct",
  },
  huggingface: {
    host: "router.huggingface.co",
    env: "HF_TOKEN",
    model: "Llama-3.3-70B-Instruct",
  },
  xai: { host: "api.x.ai", env: "XAI_API_KEY", model: "grok-3-mini" },
  custom: { host: "your-host", env: "MY_KEY", model: "my-model" },
};

const LOCAL = ["ollama", "lmstudio", "llamacpp"];
const REMOTE = Object.keys(P).filter((k) => !LOCAL.includes(k));

const esc = (s: string) =>
  s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]!);

export function initProviders() {
  const s = $("#w-state");
  const m = $("#w-msg");
  const b = $("#w-btn") as HTMLButtonElement | null;
  const cl = $("#chips-local");
  const cr = $("#chips-remote");
  const ml = $("#m-local");
  const mr = $("#m-remote");
  if (!s || !m || !b || !cl || !cr || !ml || !mr) return;

  const st = {
    mode: "local" as "local" | "remote",
    local: "ollama",
    remote: "openrouter",
    allowed: false,
  };

  const chip = (name: string, active: boolean, disabled: boolean) => {
    const li = document.createElement("li");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = name;
    btn.disabled = disabled;
    btn.setAttribute("aria-pressed", String(active));
    btn.dataset.p = name;
    li.append(btn);
    return li;
  };

  const setState = (cls: string, text: string) => {
    s.className = `state ${cls}`;
    s.textContent = text;
  };

  const render = () => {
    const local = st.mode === "local";
    const name = local ? st.local : st.remote;
    const p = P[name];
    ml.setAttribute("aria-pressed", String(local));
    mr.setAttribute("aria-pressed", String(!local));
    cl.replaceChildren(
      ...LOCAL.map((n) => chip(n, local && n === st.local, !local)),
    );
    cr.replaceChildren(
      ...REMOTE.map((n) => chip(n, !local && n === st.remote, local)),
    );

    if (local) {
      setState("local", "local · nothing leaves this machine");
      m.innerHTML =
        `<span class="dim">provider</span> ${name}\n` +
        `<span class="dim">model</span>    ${p.model}\n` +
        `<span class="dim">network</span>  ${p.host} only\n\n` +
        `<span class="dim">Remote hosts are refused before any request is made.</span>`;
      b.hidden = true;
      return;
    }

    setState("allowed", "allowed · you opted in");
    m.innerHTML =
      `${esc(`-> sending redacted, compact context to ${name} (${p.model})`)}\n\n` +
      `<span class="dim">key   ${p.env} from your environment or .env, never stored\n` +
      `data  ~2–3k tokens of redacted line windows, not your repo\n` +
      `back  --fallback ollama retries locally if this fails</span>`;
    b.hidden = false;
    b.textContent = "reset";
  };

  ml.addEventListener("click", () => {
    st.mode = "local";
    render();
  });
  mr.addEventListener("click", () => {
    st.mode = "remote";
    st.allowed = false;
    render();
  });
  b.addEventListener("click", () => {
    st.allowed = !st.allowed;
    render();
  });

  const pick = (e: Event) => {
    const t = (e.target as HTMLElement).closest(
      "button[data-p]",
    ) as HTMLButtonElement | null;
    if (!t) return;
    if (st.mode === "local") st.local = t.dataset.p!;
    else {
      st.remote = t.dataset.p!;
      st.allowed = false;
    }
    render();
  };
  cl.addEventListener("click", pick);
  cr.addEventListener("click", pick);
  render();
}
