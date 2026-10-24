# demo/

These files are produced by a **real run**, not written by hand:

```bash
ollama serve &            # if not already running
ollama pull gemma3:4b
bash scripts/make_demo.sh # writes TASKS.md, QUACK_HISTORY.md, session.log here
```
