# Cross-benchmark Agent adapters

Common host contract, real Harbor-format benchmark integrations, and the
method-native loops that run through them.

**Current milestone: adapter execution.** The requirement is that the
loader → host → agent → grader chain runs normally. Reproducing the benchmark's
own test scores is out of scope for this milestone; the real-smoke rows are
execution evidence, not method results.

## Layout

```
contract/
  types.py       TaskSpec, Action, Observation, Grade, Host, NativeAgent,
                 MethodAdapter, BenchmarkAdapter, MockHost, ScriptedAgent
  fairness.py    FairnessLedger, workflow_preserved, base_control_delta
  readiness.py   contract-ready vs real-ready matrix
benchmarks/
  harbor.py      generic Harbor loader + official tests/test.sh verifier
  tb.py          Terminal-Bench 2.1 (89 tasks)
  lhtb.py        LHTB 2.0 (46 original + 31 new tasks)
  core.py        CORE-Bench real adapter (train split, easy/medium/hard)
  core_grading.py  official CORE-Bench answer grading (std-lib port)
  mle.py         MLE-bench loader/host/medal adapter (Kaggle data conditional)
  mle_grading.py medal thresholds + synthetic accuracy metric
  metr_public.py METR Task Standard cowthello adapter (CPU-only 10h task)
  content.py     text+image content adapters (Office/Chart/Slide/Poster/ECHO/Lean)
  formal_math.py miniF2F + ProofNet on the pinned v4.33.1 project
  base.py        deterministic mock benchmarks for the contract tests
  manifest.py    real LocalHost task manifest
agents/
  base_react.py  base terminal actor
  sentry.py      official SentryRunner loop (detector/verifier/updater)
  recuris.py     Recuris Skill Memory + completion gate
  rrsi.py        prompt-only RRSI candidate (Evaluate half)
  spine.py       reimplemented Spine subtask tree (not the Pi/Node plugin)
hosts/
  local.py       LocalHost + file/command verifier
  docker.py      DockerHost + official-test copy/exec helpers
methods/
  adapters.py    Base, Sentry, Spine, Recuris, RRSI, openJiuwen, LHH, Opera
tests/
  test_adapters.py       contract/fairness/workflow invariance
  test_harbor.py         real TB 2.1 + LHTB loaders and official grading
  test_native_loops.py   Sentry/Recuris/RRSI offline loop smoke
  test_real_host.py      LocalHost / manifest / DockerHost / base ReAct
  test_core.py           CORE-Bench loader/grading/Docker smoke
  test_mle.py            MLE-bench loader/medal/synthetic submission
  test_spine.py          Spine reimplementation protocol
  test_submit_guard.py   agents continue after a rejected submit
  test_non_interference.py  no gold/hidden data or strategy changes
verify_adapters.py       adapter-only verification (no benchmark tests)
protocols/
  core-test-pilot.json   frozen CORE test-split method pilot
  tb-recorder-pilot.json two-task recorder smoke
  coverage-1m.json       4 benchmarks x 4 methods at a 1M token budget
  coverage-30m.json      4 benchmarks x 4 methods at a 30M token budget
  coverage-30m-pilot.json  single 30M-token LHTB 2048 Base pilot
  coverage-cowthello-10h.json      cowthello main_smooth, Base, 30M/12h
  coverage-cowthello-10h-all.json  cowthello main_smooth, 4 methods, multi-day
  cowthello-smoke.json   cowthello adapter wire-up smoke
  content-smoke.json     OfficeEditBench/ChartQA/ChartMimic/PPTEval smoke
  math-smoke.json        PutnamBench Lean task with model release for grading
  math-informal-smoke.json  MATH-500 + AIME fixture wire-up smoke
  math-informal-real.json   20 MATH-500 + 10 AIME 2024 real-data pilot
  math-batch-smoke.json  two-phase Putnam/miniF2F/ProofNet collect+grade smoke
  coverage-smoke.json    four-benchmark runner wire-up smoke
  coverage-compaction-smoke.json  tiny-window end-to-end compaction smoke
recording.py             trajectory recorder, heartbeat, model host, loop detection
context_policy.py        shared context-window policy (all methods, ModelClient boundary)
repro_runner.py          protocol-driven real runner with full trajectory
repro_matrix.py          four-benchmark matrix runner: ledger, resume, digests
repro_core_pilot.py      runs the CORE test-split method pilot
repro_mle_synthetic.py   MLE synthetic coverage pilot
repro_math_pilot.py      PutnamBench pilot; releases/restores the model server
                         around formal Lean grading
repro_math_batch.py      two-phase formal runner: collect solutions with the
                         server up, release it once, grade the whole batch
prepare_formal_math.py   copies miniF2F/ProofNet statements into the pinned
                         project; optional --precheck compatibility run
prepare_informal_data.py downloads MATH-500 and AIME 2024 real data
start_llama_text.sh      Linux/5090 text-mode llama-server launcher
coverage_matrix.py       summarizes the 4 x 4 coverage matrix
```

## Contract

A method only sees `Host`: `step(Action) -> Observation`, `submit()`, and the
token budget. It cannot read hidden checks and cannot call `grade()`.
The benchmark adapter holds the verifier and calls `grade()` only after the
method stops.

An adapter translates the method's native action/observation schema to the
common `Action`/`Observation`. It does not add, remove or reorder actions and
does not change the token budget, tools or grading.

## Reproduction fidelity

The adapter layer is required to be transparent to the method:

- only maps action/observation/submit schemas; no add/drop/reorder;
- same model, token budget, tools and grading for every method;
- `TaskSpec.metadata` carries no checks, answers, gold, tests or solutions;
- `Host` exposes no checks, answers, gold or hidden tests;
- `submit_guard` is **off by default**; strict submission is opt-in with
  `enforce_submission=True` and is reported as a separate condition;
- native and reimplemented loops are separate; the Spine reimplementation is
  not the official Pi/Node plugin;
- benchmark-specific environment deviations are documented in the report.

Run the adapter verification without benchmark reproduction tests:

```bash
.cache/venv/Scripts/python.exe experiments/adapters/verify_adapters.py
```

It refreshes the 32-row matrix/readiness and writes
`results/adapter-verification.json`.

## Method reproduction pilot

`protocols/core-test-pilot.json` freezes the first run on the **official CORE
test split**: 3 small tasks, Base/Sentry/Recuris m0-gate/RRSI, one attempt,
8 steps × 512 tokens, no submit guard, official `report.json` grading.

```bash
.cache/venv/Scripts/python.exe experiments/adapters/repro_core_pilot.py
```

Per-run records are in `results/core-test-pilot/`; the summary is
`results/core-test-pilot/summary.json`.

First pilot result (12 runs): one pass (Sentry on `capsule-4180912`, 2/2
checks); 10/12 runs ended without writing `report.json`; one Sentry run
answered a vision question incorrectly. This is a short pilot, not a method
conclusion. The pilot also found and fixed a real adapter bug: non-UTF-8
container output crashed the old locale-decoded subprocess path.

## Benchmark coverage pilot

`results/method-benchmark-coverage.json` records 4 benchmarks × 4 implemented
methods. All 16 combinations produced a **valid** grade (execution + official
grading chain works; pass/fail is separate):

| Benchmark | Task | Base | Sentry | Recuris-gate | RRSI |
| --- | --- | ---: | ---: | ---: | ---: |
| TB 2.1 | `regex-log` | 0/1 | 0/1 | 0/1 | 0/1 |
| LHTB 2.0 | `2048` | 0/1 | 0/1 | 0/1 | 0/1 |
| CORE test split | `capsule-4180912` | 0/2 | **2/2** | 0/2 | 0/2 |
| MLE synthetic | `synthetic` | 1/1 | 1/1 | 1/1 | 1/1 |

MLE is a **synthetic** competition because real Kaggle data is not present.
The official Spine plugin, openJiuwen, LHH and Opera remain contract-only; they
are covered by the 32-row contract matrix, not by this real coverage pilot.
Model endpoint errors are recorded as `agent_error` and the run still produces
a grade; they do not crash the harness.

## Trajectory recorder pilot

`protocols/tb-recorder-pilot.json` runs Base on TB `regex-log` and LHTB `2048`
with `repro_runner.py`. The recorder writes `trajectory.jsonl` with model
request/response, action, observation and submit events, plus
`agent-result.json` and `grading/result.json`; raw files stay in
`.cache/adapters/tb-recorder-pilot/`, the summary is
`experiments/adapters/results/tb-recorder-pilot/summary.json`.

| Task | Termination | Tokens | Valid | Checks |
| --- | --- | ---: | --- | --- |
| TB `regex-log` | `timeout_wall` (300 s) | 15,895 | true | 0/1 |
| LHTB `2048` | `timeout_tokens` (50k) | 50,555 | true | 0/1 |

The 50k token cap is already reached on LHTB; a formal corpus needs a cap above
the pilot P90. This is a recorder smoke, not the 50-task corpus.

`protocols/tb-pilot-100k.json` is the 100k-token, 3-task Base pilot:

| Task | Termination | Tokens | Agent s | Actions | Valid |
| --- | --- | ---: | ---: | ---: | --- |
| TB `regex-log` | `timeout_tokens` | 105,500 | 704.5 | 9 | true |
| TB `sqlite-db-truncate` | `timeout_tokens` | 108,404 | 386.0 | 9 | true |
| LHTB `2048` | `timeout_tokens` | 103,358 | 53.0 | 24 | true |

All three are stopped by the 100k token budget, not by wall-clock. Totals are
slightly above 100k because the final call is charged before the budget check.
If the corpus should be less budget-truncated, raise the cap to 120k+; the
current protocol keeps 100k as requested. Summary:
`experiments/adapters/results/tb-pilot-100k/summary.json`.

## Long-horizon matrix and shared context management

`protocols/coverage-1m.json` freezes **4 benchmarks × 4 methods** with one
representative task each (`tb21/regex-log`, `lhtb2/2048`,
`core/capsule-4180912`, `mle/synthetic`), a **1,000,000 cumulative-token
budget** and the shared context policy. 1M is a budget cap, not a target: a
run ends on submit, loop, context overflow, wall clock or the budget, and the
actual token count is recorded.

The local `qwen3.5-9b` server reports `n_ctx = 16384`. Cumulative tokens and
the per-request window are different quantities: the methods' native loops
append history without compaction, so on verbose tasks a request would hit the
16k window long before the cumulative budget. The shared
`context_policy.py` bounds the prompt at the `ModelClient` boundary:

- system messages and the first user message (the task) are preserved;
- each other message is capped head+tail (`max_message_chars`);
- above `trigger_ratio × window_tokens`, the oldest messages are folded into
  one deterministic digest (no model call), the most recent
  `keep_recent_messages` stay verbatim;
- every run records the compacted prompt (`model_request_sent`) and a
  `context_compact` event with before/after estimates.

This is **harness infrastructure, not a method capability**: the protocol and
`run-config.json` record it, and `--no-context` runs the same matrix as a
native ablation. It is deliberately analogous to the opt-in `submit_guard`:
the condition is reported separately, never folded into a method's score.

`repro_matrix.py` runs the matrix with an append-only ledger
(`run-ledger.jsonl`), per-run `digest.json`, and heartbeat files. Completed
`(round, benchmark, task, method)` keys are skipped on restart; interrupted
partial runs are archived and retried. Claude/humans read `summary.json`,
`matrix.json` and `--status`, not the raw trajectories.

Smoke evidence (2026-11-13, local `qwen3.5-9b`):

| Protocol | Runs | Result |
| --- | ---: | --- |
| `coverage-smoke.json` | 4 (Base, one per benchmark) | 4/4 valid grades, 0 failures, 9–60 s each |
| `coverage-compaction-smoke.json` | 1 (Base/LHTB 2048, 4k window) | 17,326 cumulative tokens, 5 compactions, max prompt 2,099, 0/1 |

The compaction smoke is the direct proof that a run can accumulate far more
than the per-request window: prompts stayed under 4,000 while cumulative charge
reached 17,326.

```bash
# one-run-per-key, resumable; --workers 2 interleaves Docker-heavy runs
.cache/venv/Scripts/python.exe experiments/adapters/repro_matrix.py \
  experiments/adapters/protocols/coverage-1m.json

# compact status without running anything
.cache/venv/Scripts/python.exe experiments/adapters/repro_matrix.py \
  experiments/adapters/protocols/coverage-1m.json --status

# native ablation (no shared context policy)
.cache/venv/Scripts/python.exe experiments/adapters/repro_matrix.py \
  experiments/adapters/protocols/coverage-1m.json --no-context
```

On Windows, `run-coverage-1m.bat` in the repo root is a double-click launcher.
It checks that Docker is running, opens its own console (so Claude Code's
background memory reaper cannot stop it), tees to a timestamped log, and
offers: 1 full 1M 4×4, 2 LHTB+CORE+MLE only, 3 TB only, 4 status, 5 exit,
6 remove leftover `adapter-*` containers, 7 rerun all 16 fresh, 8 rerun only
`tb21/rrsi`, 9 the cowthello 10h Base pilot, 10 cowthello with all four
methods. With no input it starts the full resumable 1M batch after 15 s.

`coverage-30m.json` and `coverage-30m-pilot.json` are kept for reference, but
a single small benchmark is **not** a meaningful 10h exploration task: LHTB
2048 just keeps playing, CORE/MLE submit early, and TB is too slow to reach
30M in 12h. Measured rates are ~738 tok/s on LHTB, ~660 on CORE Sentry,
~114 on TB, ~2,038 on MLE Sentry. For a real 10h single task use the METR
cowthello adapter below. The 30M protocols do set `log_full_messages: false`:
the growing raw prompt is not written on every step (O(n²) disk), while the
exact compacted prompt stays in `model_request_sent` and every
action/observation stays in the trajectory.

### Token accounting: P/rho + G

Raw cumulative tokens are not comparable across agents with different P:G
ratios. The runner records an equivalent-token cost:

```
E = P / rho + G,    rho = prefill_tps / decode_tps
T_LLM ~= E / decode_tps
```

On the local 9B, measured prefill is ~694 t/s and decode ~10.8 t/s, so
`rho ~ 65` (protocols set `prompt_equivalent_divisor: 65`). A 10h run at 10 t/s
is therefore an equivalent budget of **~360k**, independent of the P:G mix.
The matrix reports `tokens` (raw P+G), `gen` (G) and `equiv` (E). For example,
a raw 1M run with P:G ~330:1 has E ~18k, not 1M; the raw number is mostly
re-sent prompt. `E` is a cold-prefill upper bound: llama.cpp reuses KV-cache
prefixes, so measured E/s can exceed the decode rate and the actual wall clock
is below `E / decode_tps`.

A protocol can set `equivalent_budget`; the managed client raises
`equivalent token budget exceeded` when E crosses it and the runner records
`termination=timeout_equivalent`. The raw `token_budget` remains a safety cap.
The cowthello protocols use `equivalent_budget: 600000` (≈30M raw at
cowthello's P:G ≈ 186:1), `token_budget: 100M` as a safety and an 18h wall
clock as a last resort.

Raw trajectories stay in `.cache/adapters/coverage-1m/` (or `coverage-30m/`);
the small digests and matrix are in `experiments/adapters/results/coverage-1m/`
(or `coverage-30m/`).

## Long-horizon single task: METR cowthello

The four benchmark adapters above are short tasks. For a true 10h single task,
`benchmarks/metr_public.py` adapts METR's public **cowthello** (Task Standard,
MIT; the repo is marked deprecated but remains public and runnable):

- human expert built `ai_advanced` in 10 hours; full score estimated 5–15h;
- CPU-only, 1 CPU / 4 GB / 32 GB, so it does not contend with the local 9B GPU;
- official score: `0.1*winrate_random + 0.3*winrate_simple + 0.6*winrate_advanced`,
  with a 1.1x speed constraint.

The adapter extracts the official task dict and instruction from the pre-built
image `metrevals/public-tasks:cowthello-2.0.2`, runs `TaskFamily.start()` as
root, runs the method's shell actions as the `agent` user in `/home/agent` (the
official score checks the submission owner), and grades with
`TaskFamily.score()`. The official `extract_metrics` divides by a measured
time; on a fast host both sides can be `0.00`, causing `ZeroDivisionError`.
The adapter injects an equivalent zero-time guard (0/0 → 1.0, non-zero/0 → inf)
at grade time without editing the image; this is the only scoring deviation.

Smoke (Base, 20k tokens, 6 steps): official smooth score **0.080**, valid.
The initial `ai_random` baseline scores ~0.06, so the task leaves room to
measure progress.

```bash
# adapter smoke
.cache/venv/Scripts/python.exe experiments/adapters/repro_matrix.py \
  experiments/adapters/protocols/cowthello-smoke.json

# long-horizon Base pilot (E=600k, raw safety 100M, 18h wall clock, CPU-only)
.cache/venv/Scripts/python.exe experiments/adapters/repro_matrix.py \
  experiments/adapters/protocols/coverage-cowthello-10h.json
```

Why not RE-Bench/HCAST here: RE-Bench's task manifests require an H100 with
100 GB RAM and CUDA; the local machine has an RTX 3050 6 GB (Vulkan, no CUDA).
HCAST's public repo releases only 11 task families / 28 tasks and withholds the
full 189, so it cannot supply a 10h task. Both remain options for an H100
server; cowthello is the local single-task long-horizon path.

### Local VLM for PPT evaluation

The local `qwen3.5-9b` GGUF is natively multimodal; the original text-only
launch omitted the matching projector. `.cache/models/mmproj-F16.gguf`
(918 MB, SHA256 `f70dc…029f`) is the projector for the exact checkpoint
(model SHA256 `03b747…b7e8`). Two launchers live in this directory:

- `start_llama_vlm.ps1 -Ngl 22`: vision + text; measured prefill ~603 t/s,
  decode ~7.6 t/s, VRAM 5,756/6,144 MiB; image request passed. 20 layers is
  the higher-headroom fallback (~6.5 t/s).
- `start_llama_text.ps1 -Ngl 26`: text-only, decode ~10.8 t/s.

PPT edits remain `python-pptx`/terminal; the VLM is only used to evaluate or
feed back on rendered slides, never to drive a GUI. The local renderer is WPS
Presentation COM (`render_pptx_wps.ps1`); no LibreOffice/PowerPoint is needed.
Rendered files are `幻灯片N.PNG`.

PPT chain smoke (2026-11-14, `results/ppt-smoke/summary.json`): a
`python-pptx` deck → WPS COM PNG (1600×900) → VLM PPTEval review. The VLM
returned content=3, design=2, coherence=4 and correctly identified the
deliberate inconsistent font sizes, the dense first paragraph, the 6pt
footer and text overflow, with concrete fixes. Use text-only mode for the
benchmark matrix when vision is not needed.

## Text+image content adapters

`benchmarks/content.py` implements the AIGC text+image suite (no GUI computer
use). `LocalContentHost` runs file/shell/submit actions in a temp workspace and
installs `vision.py`, which sends rendered charts/slides to the local VLM;
agent-visible feedback and the hidden VLM judge are separate. `vlm_tokens` is
recorded in each run.

| Adapter | Data | Grade | Status |
| --- | --- | --- | --- |
| `office_edit` | OfficeEditBench real tasks | official `verify_task.py` | easy real; medium/hard pending |
| `chartqa` | ChartQA `test_human` + images | relaxed exact match | real |
| `chartmimic` | local fixture (optional image set) | execution + VLM visual fidelity | local fixture |
| `ppteval` | local deck fixture | WPS render + VLM Content/Design/Coherence | local |
| `paper2poster` / `deckbench` | local fixtures | render + VLM visual/textual/holistic | local |
| `echo` | local co-edit fixture | intent/title/subtitle checks | local reimplementation; no official code/data |
| `math500` | local MATH-500 JSON or 2-problem fixture | `\boxed` / fraction / numeric exact match | real loader hook; fixture offline |
| `aime` | local AIME JSON or 2-problem fixture | integer 0-999 exact match | real loader hook; fixture offline |
| `putnam` | PutnamBench Lean 4 sources | `lake env lean` + cheat check | Lean 4.33.1 + Mathlib ready; grading needs ~5.5 GB free commit |

`protocols/content-smoke.json` runs Base on one task from each of OfficeEditBench
easy, ChartQA, ChartMimic and PPTEval at a 20k budget. Smoke result (6 steps):
4/4 valid chain; OfficeEditBench 0/1, ChartQA **1/1** (used `vision.py`),
ChartMimic 0/2 (used `vision.py`), PPTEval 0/1 (deck missing). This is execution
evidence, not a method result.

### Formal math (PutnamBench / Lean 4)

`putnam` grades by compiling the task file with the pinned Lean 4.33.1 +
Mathlib in `.cache/tools` and rejecting `sorry`, `admit`, and new
`axiom`/`constant`/`opaque`/`unsafe` declarations before the kernel runs.
The adapter prefers the bundled toolchain over the `elan` shim, which can
block on a toolchain download even when v4.33.1 is installed.

Full `import Mathlib` maps about 3.5 GB of oleans and needs roughly **5.5 GB
of free commit charge**. With the resident 9B server the host has about 1 GB,
and Lean fails on a random `.olean.private` with a read error. The math pilot
makes this explicit:

```bash
python experiments/adapters/repro_math_pilot.py \
  experiments/adapters/protocols/math-smoke.json --release-model
```

`--release-model` stops `llama`, waits for commit headroom, grades, then
restarts the server from `start_llama_text.ps1` and health-checks it.
`--grade-only` re-grades the current Lean project after an interrupted run.
The opt-in `RUN_LEAN_TESTS=1` test creates a trivial solved task and proves the
full compile path; it is skipped by default because the server must be stopped
first.

### miniF2F / ProofNet and the two-phase runner

Setup (once; both repos are small statement-only checkouts):

```bash
git clone --depth 1 https://github.com/yangky11/miniF2F-lean4 .cache/upstream/minif2f-lean4
git clone --depth 1 https://github.com/rahul3613/ProofNet-lean4 .cache/upstream/proofnet-lean4
python experiments/adapters/prepare_formal_math.py
```

`prepare_formal_math.py` copies the upstream Lean 4 statements into the pinned
v4.33.1 project:

| Dataset | Upstream @ commit | Files / tasks | Grading |
| --- | --- | --- | --- |
| miniF2F | `yangky11/miniF2F-lean4` @ `5746b7d` | 488 files (244 Test + 244 Valid), one theorem each | file-level `lake env lean` |
| ProofNet | `rahul3613/ProofNet-lean4` @ `6deae98` | 360 theorems in 11 textbook files; **66 usable** after v4.33 precheck | per-theorem warning mapping |

Both upstream ports pin older toolchains (v4.24.0 / v4.20.0). Compiling their
statements with the same v4.33.1 Mathlib as PutnamBench keeps the formal suite
comparable; `--precheck` compiles every file with its original `sorry` and
`precheck.json` makes the loaders skip incompatible files. Precheck results:
miniF2F **20/20** sampled Test files compile; ProofNet **5/11** files compile
(Cambridge-Tripos, Ireland-Rosen, Pugh, Putnam, Shakarchi = 66 theorems). The
six excluded files (Artin, Axler, Dummit-Foote, Herstein, Munkres, Rudin) use
pre-v4.33 Mathlib API. A full 488-file miniF2F precheck is still to run.

`MiniF2FAdapter` is file-level. `ProofNetAdapter` exposes one task per theorem:
grading runs Lean once per file and maps `declaration uses 'sorry'` warning
lines back to the target theorem block, so other theorems may keep their
`sorry`.

For 100–200 Putnam or 488 miniF2F tasks, restarting the server per task is too
expensive. `repro_math_batch.py --phase all --release-model`:

1. **collect** every (task, method) with the server up, saving `solution.lean`
   and `pristine.lean` per run;
2. **grade** the whole batch after one server stop, replaying each solution
   into the project, compiling, restoring the pristine file, then restarting
   the server.

The runner is resumable and `--status` reports collected/graded counts.

`RUN_LEAN_TESTS=1` also compiles a miniF2F trivial theorem and a ProofNet
fixture with one solved and one still-`sorry` theorem; the solved one passes
and the `sorry` one is rejected (168.9 s for the full test).

Batch smoke (2026-11-14, 4 steps each): 2 Putnam + 1 miniF2F + 1 ProofNet,
4/4 collected (all `max_steps`, 1–3 actions, 3.3k–7.0k tokens) and 4/4 graded
valid 0/1 because every solution still contained `sorry`. The grade phase
stopped the server once (commit 4.27 → 5.8 GB; the 6.0 GB threshold waited its
full 90 s because Docker was also running), graded all four, and restarted the
server in 8.1 s. Closing Docker Desktop raises the post-release headroom to
about 8 GB and avoids that wait.

On the Linux 5090 host (62 GB RAM) the model server and Lean can coexist, so
the batch runner can grade with the server up (omit `--release-model`). Build
`llama-server` with CUDA 12.9 and `-DCMAKE_CUDA_ARCHITECTURES=120`; start it
with `start_llama_text.sh` (`-ngl 99`). Put the Linux Lean toolchain under
`.cache/tools/lean4-4.33.1/lean-4.33.1-linux/bin`; the resolver checks that
path on Linux.

### Informal math (MATH-500 / AIME)

`math500` and `aime` load a local JSON/JSONL file (fields `problem` and
`answer`) or a two-problem fixture. The agent works in a temp workspace and
writes `answer.txt`; grading takes the last `\boxed{...}` (or last line) and
matches exact strings, decimals within a relative tolerance, and fractions by
cross-multiplication. AIME answers must be integers in 0–999.
`protocols/math-informal-smoke.json` runs Base on one fixture task each; it is
a wire-up smoke, not a benchmark result. `answer.txt` is the graded artifact:
in the 2026-11-14 smoke the AIME task wrote it and passed (1/1, 603 tokens),
while the MATH-500 task put the correct `5` only in the final channel and was
recorded as 0/1 (`answer.txt` missing), which is an instruction-following
failure rather than a grading bug.

Real data is ready in the ignored cache: MATH-500 `test.jsonl` (500 problems)
at `.cache/upstream/math500/test.jsonl` and AIME 2024 (30 problems) at
`.cache/upstream/aime/aime_2024.jsonl`. `protocols/math-informal-real.json`
uses `"discover": true` to take the first 20 MATH-500 and 10 AIME tasks.

## Real benchmarks

Both datasets use the same Harbor task layout (`task.toml`,
`instruction.md`, `environment/`, `tests/`):

| Adapter | Root (ignored cache) | Tasks | Official tests |
| --- | --- | ---: | ---: |
| `TerminalBench21Adapter` | `.cache/upstream/terminal-bench-2-1/tasks` | 89 | 89 |
| `LHTBBenchmarkAdapter(subdir="tasks")` | `.cache/upstream/lhtb/tasks` | 46 | 46 |
| `LHTBBenchmarkAdapter(subdir="tasks-2.0")` | `.cache/upstream/lhtb/tasks-2.0` | 31 | 31 |
| `CoreBenchAdapter` | `.cache/upstream/core-bench` (train split) | 45 | 45 |
| `MLEBenchAdapter` | `.cache/upstream/mle-bench` (low split) | 22 | conditional |

The LHTB `tasks-2.0` private verifier files are present in the public checkout;
they are copied into the container only after the method stops, so the method
never sees them.

CORE-Bench uses the public **train** split (45 tasks); the held-out test split
is GPG-encrypted. Capsules are downloaded lazily from
`corebench.cs.princeton.edu` (the full set is ~13 GB) and are not committed.
The first integration targets `codeocean_easy` (answer from `results/` without
running code); medium/hard share the same host and official `report.json`
grader.

MLE-bench loads the 22-competition **low** split and the official competition
descriptions. Real Kaggle data and the official per-competition metric require
the `mlebench` package (pandas etc.) and Kaggle credentials; without them the
adapter reports the missing dependency. The host and medal logic are tested
with a synthetic competition and a dependency-free accuracy metric.

## Official grading

`OfficialTestVerifier` starts the task image, copies the official `tests/`
directory to `/tests` after the method stops, runs `tests/test.sh`, and reads
`/logs/verifier/reward.txt`. It does not recompute the score. A missing reward
file yields an invalid grade, never a fake pass. Shell scripts are staged with
LF line endings so Windows checkouts behave like Linux checkouts.

CORE and MLE support an optional `submit_guard`: when
`enforce_submission=True`, `submit` is rejected until `report.json` /
`submission.csv` exists. It is off by default because it adds host feedback;
guard/no-guard runs are separate conditions.

## Native loops

| Method | Loop | What runs | What does not run |
| --- | --- | --- | --- |
| Base | `base_react.py` | one terminal action per turn, then submit | — |
| Sentry | `sentry.py` | official `SentryRunner` detector/verifier/updater | original AppWorld driver |
| Recuris | `recuris.py` | fixed `tb21_seed` Skill Memory + `check_completion` gate | tta meta-agent patch loop |
| RRSI | `rrsi.py` | prompt-only candidate, scored by the official verifier | search loop (needs Anthropic Vertex) |
| Spine (reimpl) | `spine.py` | Python subtask tree: `spine_open/close/next`, closed-branch history folded into memory | official Pi/Node plugin bridge; `spine_spawn` execution |
| Spine (official) | — | contract adapter only | Pi + `spine_*` native loop |
| openJiuwen / LHH / Opera | — | contract adapter only | native loops |

## Run the tests

The native loops import the upstream Sentry/Recuris checkouts, which need
`pyyaml` and `loguru`; the project venv has them:

```bash
.cache/venv/Scripts/python.exe -m unittest discover \
  -s experiments/adapters/tests -t experiments/adapters -v
```

Current result: **94 tests, all pass**. Coverage:

- four mock benchmarks run the base agent;
- seven method adapters run on all four mock benchmarks;
- native vs adapted action sequences are identical (workflow invariance);
- methods do not access hidden checks and do not call `grade()`;
- `submit_guard` is off by default; strict submission is opt-in, and agents
  continue after a rejected submit;
- the non-interference audit finds no gold/answers/checks in method-visible
  metadata or Host, and adapter changes are schema mappings only;
- Docker/Local hosts decode arbitrary command output as UTF-8 with replacement,
  so non-UTF-8 benchmark data cannot crash a reproduction run;
- the shared context policy keeps system + task + recent messages, folds older
  turns into a deterministic digest, truncates long observations, and never
  calls the model to compact;
- managed clients raise `context_overflow` (not a fake run) when the prompt
  cannot be reduced, and Base ReAct completes through the wrapper;
- all adapters use the same config/token budget;
- base + adapter control delta is computed;
- the 4 × 8 adapter matrix is complete;
- readiness is honest about which methods have native loops;
- LocalHost + manifest + Base ReAct and DockerHost run real tasks end-to-end;
- TB 2.1 loads 89 official tasks; LHTB loads 46 + 31;
- the official `tests/test.sh` reward path passes and fails correctly;
- a failed pytest summary is not turned into a pass when `test.sh` exits 0
  (LHTB 2048 does this); CTRF, then the pytest summary, then the exit code;
- a method that plants `/logs/verifier/reward.txt` cannot keep it;
- CORE-Bench loads the 45-task train split and does not leak gold answers;
- CORE-Bench numeric (95% PI), string and list grading works, and a synthetic
  capsule round-trips through Docker to a passing `report.json`;
- CORE-Bench medium/hard environment preparation keeps/removes the right files
  and empties `results` before grading;
- Sentry, Recuris (m0/m0-gate) and RRSI run offline on a manifest task;
- the Spine reimplementation opens/closes/nexts branches and folds closed
  history into memory; `spine_spawn` is recognized but not executed;
- MLE-bench loads the 22-competition low split, computes official medal
  thresholds, and grades a synthetic submission through Docker to a medal;
- METR cowthello loads its official task/instruction from the pre-built image,
  runs agent shell commands as the `agent` user, and returns an official
  smooth score (zero-time guard applied);
- the content host runs file/shell/submit actions and installs the `vision.py`
  VLM tool;
- OfficeEditBench easy runs the official `verify_task.py`; ChartQA uses relaxed
  exact match on a real test sample;
- ChartMimic/PPT/ECHO fixtures execute code, render decks, and grade with
  injected VLM judges;
- PutnamBench loads Lean 4 tasks and rejects `sorry`/`admit`/new axioms;
  `RUN_LEAN_TESTS=1` additionally compiles a trivial solved task with the
  pinned Lean 4.33.1 + Mathlib (the model server must be stopped first);
- miniF2F/ProofNet loaders expose 488 file-level and 360 per-theorem tasks;
  the per-theorem grader maps Lean's `sorry` warnings back to the target block,
  and `RUN_LEAN_TESTS=1` compiles a trivial solved theorem plus a still-`sorry`
  theorem.

## Generate the evidence

```bash
python experiments/adapters/export_matrix.py
python experiments/adapters/preflight.py
```

- `results/adapter-verification.json` — adapter-only verification: test result,
  32-row contract matrix, readiness and non-interference checklist.
- `results/adapter-matrix.json` — 32 contract runs (4 benchmarks × 8 methods).
- `results/adapter-readiness.json` — 32 combinations, missing items per row.
- `results/adapter-datasets.json` — task counts and real-loader/host/grader flags.
- `results/real-integration.json` — real dataset inventory, native-loop
  readiness, offline test status, and the TB 2.1 / LHTB / CORE / MLE smokes.
- `results/real-smoke-9b.json` — six real 9B runs (TB Base; CORE Base, Sentry,
  Recuris m0, Recuris m0-gate, RRSI) with action logs and official grades.
- `results/method-benchmark-coverage.json` — 4 benchmarks × 4 implemented
  methods, all with valid execution+grading (`16/16`).
- `experiments/adapters/results/tb-recorder-pilot/summary.json` — two-task recorder smoke with
  termination reason, tokens and official grade.
- `experiments/adapters/results/tb-pilot-100k/summary.json` — three-task Base pilot at the 100k token
  budget; all three ended in `timeout_tokens` (valid, 0/1).
- `experiments/adapters/results/math-smoke/summary.json` — PutnamBench one-task
  Base smoke; records the model release, free commit before/after grading, and
  the Lean compile grade.
- `experiments/adapters/results/math-informal-smoke/summary.json` — MATH-500 +
  AIME fixture smoke; AIME 1/1, MATH-500 0/1 (artifact not written).
- `experiments/adapters/results/math-batch-smoke/summary.json` — two-phase
  Putnam/miniF2F/ProofNet collect+grade smoke; `--status` shows progress.
- `.cache/upstream/putnambench/lean4/formal/README.json` — upstream commits,
  toolchains and file counts for miniF2F/ProofNet (ignored cache);
  `precheck.json` records compatibility.
- `recording.py` / `repro_runner.py` — trajectory recorder and protocol runner;
  raw `trajectory.jsonl` stays under `.cache`.

Current readiness: contract **32/32**; real-ready **0/32** because no model
endpoint is configured in this offline round. For TB 2.1 and LHTB 2.0 the
remaining gap for Base/Sentry/Recuris/RRSI is only `model endpoint`; Spine,
openJiuwen, LHH and Opera still lack a native loop. CORE-Bench and MLE-bench
are reported as missing datasets, not mocked.

## Status

The contract layer, TB 2.1, LHTB 2.0 and the CORE-Bench train-split
execution+grading paths are implemented and tested. A real TB 2.1 `regex-log`
oracle run passed the official test 1/1 (reward 1.0) in 80.6 s; a real LHTB 2.0
`2048` blank submission was correctly scored 0/1 (reward 0.0); a synthetic and
a real CORE-Bench easy capsule (`capsule-1854976`) round-tripped through
Docker to a passing `report.json` (3/3); medium/hard environment preparation is
tested with a synthetic capsule. A real 9B smoke (Qwen3.5-9B, 6 steps × 512
tokens) produced valid official grades for Base on TB 2.1 `regex-log` (0/1) and
CORE easy `capsule-1854976` (0/3); the model repeated a wrong regex and did not
write the required `report.json`. On LHTB 2.0 `2048`, Base made five moves and
reached band 0 (largest tile 8, dense reward 0.0908), valid but below the band-1
pass threshold; Sentry, Recuris m0 and RRSI also stopped at band 0 (0/1) within
six steps. On the same CORE capsule, Sentry passed 3/3
(detector triggered 6 times) and RRSI passed 3/3; Base, Recuris m0 and Recuris
m0-gate all failed 0/3 because they submitted without writing `report.json`.
With the benchmark-side submit guard (reject `submit` until the required
artifact exists), those three reached 3/3; the guard is a host-level submission
check applied uniformly, not a model improvement. A Python Spine subtask-tree
reimplementation is
available and tested offline, but it is **not** the official Pi/Node plugin.
For formal math, the PutnamBench loader/host/grader and a real Lean 4.33.1
kernel compile are verified (a trivial solved theorem compiled in 178.7 s;
the math smoke graded a real Putnam task valid 0/1 with `--release-model`
moving commit headroom from 2.1 GB to 8.1 GB). MATH-500/AIME answer adapters,
miniF2F (488 files) and ProofNet (360 theorems) loaders are in place, with a
two-phase runner that collects under the model server and grades after one
server stop. The full miniF2F/ProofNet precheck is the remaining setup step.

MLE-bench's loader, host and medal logic are implemented and tested with a
synthetic competition; real Kaggle data and the official metric need
credentials and the `mlebench` package. CORE-Bench medium/hard and the held-out
test split, the official Spine bridge, and the remaining native loops are the
next integration step.
