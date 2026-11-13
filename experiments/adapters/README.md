# Cross-benchmark Agent adapters

Common host contract, real Harbor-format benchmark integrations, and the
method-native loops that run through them.

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
  mle.py         MLE-bench skeleton (dataset missing)
  base.py        deterministic mock benchmarks for the contract tests
  manifest.py    real LocalHost task manifest
agents/
  base_react.py  base terminal actor
  sentry.py      official SentryRunner loop (detector/verifier/updater)
  recuris.py     Recuris Skill Memory + completion gate
  rrsi.py        prompt-only RRSI candidate (Evaluate half)
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
```

## Contract

A method only sees `Host`: `step(Action) -> Observation`, `submit()`, and the
token budget. It cannot read hidden checks and cannot call `grade()`.
The benchmark adapter holds the verifier and calls `grade()` only after the
method stops.

An adapter translates the method's native action/observation schema to the
common `Action`/`Observation`. It does not add, remove or reorder actions and
does not change the token budget, tools or grading.

## Real benchmarks

Both datasets use the same Harbor task layout (`task.toml`,
`instruction.md`, `environment/`, `tests/`):

| Adapter | Root (ignored cache) | Tasks | Official tests |
| --- | --- | ---: | ---: |
| `TerminalBench21Adapter` | `.cache/upstream/terminal-bench-2-1/tasks` | 89 | 89 |
| `LHTBBenchmarkAdapter(subdir="tasks")` | `.cache/upstream/lhtb/tasks` | 46 | 46 |
| `LHTBBenchmarkAdapter(subdir="tasks-2.0")` | `.cache/upstream/lhtb/tasks-2.0` | 31 | 31 |
| `CoreBenchAdapter` | `.cache/upstream/core-bench` (train split) | 45 | 45 |

The LHTB `tasks-2.0` private verifier files are present in the public checkout;
they are copied into the container only after the method stops, so the method
never sees them.

CORE-Bench uses the public **train** split (45 tasks); the held-out test split
is GPG-encrypted. Capsules are downloaded lazily from
`corebench.cs.princeton.edu` (the full set is ~13 GB) and are not committed.
The first integration targets `codeocean_easy` (answer from `results/` without
running code); medium/hard share the same host and official `report.json`
grader.

## Official grading

`OfficialTestVerifier` starts the task image, copies the official `tests/`
directory to `/tests` after the method stops, runs `tests/test.sh`, and reads
`/logs/verifier/reward.txt`. It does not recompute the score. A missing reward
file yields an invalid grade, never a fake pass. Shell scripts are staged with
LF line endings so Windows checkouts behave like Linux checkouts.

## Native loops

| Method | Loop | What runs | What does not run |
| --- | --- | --- | --- |
| Base | `base_react.py` | one terminal action per turn, then submit | — |
| Sentry | `sentry.py` | official `SentryRunner` detector/verifier/updater | original AppWorld driver |
| Recuris | `recuris.py` | fixed `tb21_seed` Skill Memory + `check_completion` gate | tta meta-agent patch loop |
| RRSI | `rrsi.py` | prompt-only candidate, scored by the official verifier | search loop (needs Anthropic Vertex) |
| Spine | — | contract adapter only | Pi + `spine_*` native loop |
| openJiuwen / LHH / Opera | — | contract adapter only | native loops |

## Run the tests

The native loops import the upstream Sentry/Recuris checkouts, which need
`pyyaml` and `loguru`; the project venv has them:

```bash
.cache/venv/Scripts/python.exe -m unittest discover \
  -s experiments/adapters/tests -t experiments/adapters -v
```

Current result: **32 tests, all pass**. Coverage:

- four mock benchmarks run the base agent;
- seven method adapters run on all four mock benchmarks;
- native vs adapted action sequences are identical (workflow invariance);
- methods do not access hidden checks and do not call `grade()`;
- all adapters use the same config/token budget;
- base + adapter control delta is computed;
- the 4 × 8 adapter matrix is complete;
- readiness is honest about which methods have native loops;
- LocalHost + manifest + Base ReAct and DockerHost run real tasks end-to-end;
- TB 2.1 loads 89 official tasks; LHTB loads 46 + 31;
- the official `tests/test.sh` reward path passes and fails correctly;
- a method that plants `/logs/verifier/reward.txt` cannot keep it;
- CORE-Bench loads the 45-task train split and does not leak gold answers;
- CORE-Bench numeric (95% PI), string and list grading works, and a synthetic
  capsule round-trips through Docker to a passing `report.json`;
- CORE-Bench medium/hard environment preparation keeps/removes the right files
  and empties `results` before grading;
- Sentry, Recuris (m0/m0-gate) and RRSI run offline on a manifest task.

## Generate the evidence

```bash
python experiments/adapters/export_matrix.py
python experiments/adapters/preflight.py
```

- `results/adapter-matrix.json` — 32 contract runs (4 benchmarks × 8 methods).
- `results/adapter-readiness.json` — 32 combinations, missing items per row.
- `results/adapter-datasets.json` — task counts and real-loader/host/grader flags.
- `results/real-integration.json` — real dataset inventory, native-loop
  readiness, offline test status, and the TB 2.1 / LHTB official-grading smokes.

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
tested with a synthetic capsule. This round did **not** run the 9B model: all method smoke is
deterministic and offline. MLE-bench data, CORE-Bench medium/hard and the
held-out test split, and the remaining four native loops are the next
integration step.
