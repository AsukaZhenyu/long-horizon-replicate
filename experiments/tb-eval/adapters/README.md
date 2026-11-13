# TB8 adapters for external methods

These adapters let a method that was published against another benchmark run on
the local TB8 set (Terminal-Bench 0.2.18, 8 historical tasks, Qwen3.5-9B, 300 s,
one fresh attempt). They do not modify the method's algorithm source.

| Adapter | What runs | What does not run |
| --- | --- | --- |
| [`recuris/`](recuris/README.md) | m0: fixed `tb21_seed` Skill Memory injected into the Pi system prompt; 8 tasks scored by the same grader | tta completion gate and the meta-agent patch loop |
| [`rrsi/`](rrsi/README.md) | `Domain` evaluation half: score a prompt-only candidate harness on TB8 | the RRSI search loop (needs AnthropicVertex) |

Both adapters write into their own runs directory and record the adapter name in
`source.json`; they do not mix with the Sentry/Spine/Pi AB smoke evidence.

The shared host is `harness/spine/run.mjs --pi-only`; `HW_APPEND_SYSTEM_PROMPT`
adds a candidate system prompt, and `HW_ADAPTER` records the adapter label.
