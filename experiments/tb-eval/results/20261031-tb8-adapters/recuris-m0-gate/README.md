# Recuris m0-gate on TB8 (adapter run)

Fixed `tb21_seed` Skill Memory injected into the Pi 1.1.0 system prompt, plus
Recuris `check_completion` as a completion gate. The proxy turns a bounce into
a synthetic `bash` tool call that prints the correction back to the agent.

- A=4, V=4, Y=4; passes hello-world, fix-permissions, log-summary, cancel-async-tasks.
- 4 bounces; cancel-async-tasks is the task rescued by the gate. jq still fails
  because the request exceeds the 16k context window.
- This is m0-gate, not full tta: the meta-agent patch loop is not implemented.
- Adapter: `experiments/tb-eval/adapters/recuris/`.
