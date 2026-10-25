export const groups = [
  {
    name: "Ask the duck",
    cmds: [
      [
        'ask "…"',
        "--stdin --depth --provider",
        "Explain a bug and write TASKS.md. Cached for 24h, repeats cost 0 tokens.",
      ],
      [
        "chat",
        "",
        "Follow-up questions with memory. /files /model /depth /verify.",
      ],
      [
        'compare "…"',
        "-w A -w B",
        "Same question to several models, side by side. Writes no tasks.",
      ],
      ["explain FILE", "--no-llm", "What a file does, from its signatures."],
      ["review", "--since REV", "Batch review of the riskiest files."],
    ],
  },
  {
    name: "Track",
    cmds: [
      ["tasks", "", "Your to-do list. Tick a box and history notices."],
      [
        "history",
        "",
        "Weekly questions, resolved tasks, mini-lessons for repeated concepts.",
      ],
      [
        "verify",
        "--audit",
        "Prove no source file changed. --audit lists every write site.",
      ],
      ["export", "", "A readable session log you can share."],
    ],
  },
  {
    name: "Set up",
    cmds: [
      ["doctor", "", "Checks Ollama, the model, keys and the index."],
      [
        "init",
        "--provider --fallback",
        "Pick a provider. Remote ones are opt-in.",
      ],
      ["providers", "", "Every supported provider and whether it is ready."],
      ["config", "show | get | set", "Read or change .quack/config.toml."],
      ["index", "--changed --since", "Build the index. 0 tokens."],
      ["cache", "stats | clear", "Inspect or clear stored answers."],
    ],
  },
];
