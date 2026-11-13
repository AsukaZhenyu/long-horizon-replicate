# Recuris m0 on TB8 (adapter run)

Fixed `tb21_seed` Skill Memory injected into the Pi 1.1.0 system prompt for each
of the eight TB8 tasks. Same model, budget and grader as the AB smoke.

- A=3, V=3, Y=3; same passing set as Pi-only (hello-world, fix-permissions, log-summary).
- This is the m0 arm only. The tta completion gate and the meta-agent patch loop
  are not implemented; do not read this as the full Recuris result.
- Adapter: `experiments/tb-eval/adapters/recuris/`.
- Full per-task evidence (traces, tars, grading) stays in `.cache/runs-tb8-recuris/`.
