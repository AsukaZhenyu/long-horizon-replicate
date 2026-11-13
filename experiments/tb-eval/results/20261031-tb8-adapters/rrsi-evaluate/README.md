# RRSI TB8 domain adapter: self-test

The adapter's `Domain` half is implemented in
`experiments/tb-eval/adapters/rrsi/adapter.py`. It was installed into the local
RRSI checkout and exercised end-to-end.

- `smoke`: 8 task images + candidate prompt present.
- 2-task run smoke: hello-world + fix-permissions, A=2/V=2/Y=2 (`smoke-cases/`).
- 8-task Evaluate: A=3/V=3/Y=3, passing hello-world, fix-permissions, log-summary (`eval8-cases/`).
- The RRSI search loop (proposer/analyst/critic) is **not run**: upstream
  `rrsi/llm.py` requires AnthropicVertex.

The 8-task Evaluate uses a prompt-only candidate harness; it is not an RRSI
search-loop result and cannot be read as the method's gain.
