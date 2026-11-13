# TB8 harness skill

The downstream agent is Pi 1.1.0 running against a local Qwen3.5-9B Q4_K_M.
It receives one Terminal-Bench 0.2.18 task instruction, a fresh container, a
300 s total budget, and no hidden tests. It must leave the required artifact in
`/app` and submit.

The editable harness is `domains/tb8/harness/system_prompt.txt`. It may change
planning, command construction, validation discipline, and when to submit. It
must not change the task instruction, the container image, the model, the
budget, or the grading path.
