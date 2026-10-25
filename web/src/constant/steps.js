export const steps = [
  {
    n: "01",
    name: "Index",
    text: "Walks the repo with the filesystem, regex and SQLite. Symbols, term counts, TODOs. No model involved.",
    cost: "0 tokens",
  },
  {
    n: "02",
    name: "Retrieve",
    text: "BM25 over the index, plus a bonus for matching symbol and file names. Pipe in a traceback and the files it names are pinned.",
    cost: "local",
  },
  {
    n: "03",
    name: "Window",
    text: "Only line windows around matching symbols, capped at 30 / 80 / 150 lines per file by depth. Never a whole file.",
    cost: "local",
  },
  {
    n: "04",
    name: "Redact",
    text: "API keys, GitHub and Slack tokens, AWS keys and private keys are masked before anything reaches a model.",
    cost: "local",
  },
  {
    n: "05",
    name: "Ask",
    text: "One call to the model, structured JSON back: a question, a cause, tasks, concepts, confidence.",
    cost: "the model",
    model: true,
  },
  {
    n: "06",
    name: "Ground",
    text: "Tasks that point at files that don't exist are dropped. Impossible line numbers are clamped. Then TASKS.md.",
    cost: "local",
  },
];
