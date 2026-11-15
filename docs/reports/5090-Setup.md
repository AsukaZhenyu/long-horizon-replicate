# RTX 5090 host setup

## Host

- SSH: `lzy@172.17.140.170` (alias `gpu5090`), key `~/.ssh/id_ed25519_5090`
- Hostname `fchpc`; Ubuntu 22.04.4, kernel 6.8
- GPU: NVIDIA GeForce RTX 5090, 32,607 MiB, compute capability 12.0,
  driver 580.178.04 / CUDA 13.0
- 128 CPU cores, 62 GB RAM, 1.5 TB free on `/`
- No sudo and **no direct internet**; data is transferred from the local
  machine over the lab network.

## llama.cpp / model

- Source: `/home/lzy/work/llama.cpp-b8705`
- Built with CUDA 12.9 (`/usr/local/cuda-12.9`) and
  `-DCMAKE_CUDA_ARCHITECTURES=120`, `-DLLAMA_CURL=OFF`:
  `build/bin/llama-server` (CUDA0: RTX 5090, 31588 MiB free).
- Runtime libraries:
  `LD_LIBRARY_PATH=/usr/local/cuda-12.9/lib64:<llama>/build/bin`.
- Model files in `~/long-horizon-replicate/.cache/models`:
  `qwen3.5-9b-q4_k_m.gguf` (5.3 GB) and `mmproj-F16.gguf` (876 MB).
- Start text-only mode with
  `bash experiments/adapters/start_llama_text.sh` (`-ngl 99`, `-c 16384`,
  port 8080). The 62 GB host can keep the server up while Lean grades, so the
  math batch runner does **not** need `--release-model`.

## Lean

- Linux Lean 4.33.1 at
  `~/long-horizon-replicate/.cache/tools/lean4-4.33.1/lean-4.33.1-linux/bin`.
- The PutnamBench project (Mathlib v4.33.1, built on the local host) is
  transferred to
  `~/long-horizon-replicate/.cache/upstream/putnambench/lean4`; the `.olean`
  files are portable across platforms for the same Lean version.
- miniF2F/ProofNet statements and `formal/precheck.json` are inside that
  project.

### Lake wrapper (important)

The first transfer excluded `.lake/packages/*/.git`.  On the first
`lake env lean`, Lake concluded that the Mathlib URL had changed and
**deleted `.lake/packages/mathlib`** before trying to re-clone it (there is no
internet or git on this host).  Recovery: re-transfer `.lake/packages` with its
`.git` directories, and run Lean through `lake-wrapper.sh`:

```bash
mkdir -p .cache/tools/lean-wrapper/bin
cp experiments/adapters/lake-wrapper.sh .cache/tools/lean-wrapper/bin/lake
chmod +x .cache/tools/lean-wrapper/bin/lake
export PUTNAM_LEAN_BIN=$PWD/.cache/tools/lean-wrapper/bin/lake
```

The wrapper turns `lake env lean X` into the pinned `lean` with `LEAN_PATH`
set to the package build dirs, so Lake never checks git.  Verified:

- `lake-wrapper env lean src/putnam_1962_a1.lean` → rc 0 with the expected
  `declaration uses 'sorry'` warning.
- miniF2F/ProofNet `RUN_LEAN_TESTS=1` integration test → OK (7.5 s).
- `prepare_formal_math.py --precheck --only minif2f --workers 8 --no-copy`
  runs the full 488-file compatibility check.

## Local → host transfer

The local shell has no rsync/wget, but `tar | ssh` works. Examples:

```bash
tar -czf - --exclude=.git --exclude=.cache . | \
  ssh gpu5090 'mkdir -p ~/long-horizon-replicate && tar -xzf - -C ~/long-horizon-replicate'

tar -C .cache/models -cf - qwen3.5-9b-q4_k_m.gguf mmproj-F16.gguf | \
  ssh gpu5090 'mkdir -p ~/long-horizon-replicate/.cache/models && tar -xf - -C ~/long-horizon-replicate/.cache/models'
```

The Lean project is 7.3 GB locally and is sent as a gzip stream excluding
`.git` directories.

## Verification

- `llama-server` sees `CUDA0: RTX 5090 (32109 MiB, 31588 MiB free)`.
- Text-only server: 6,503 MiB VRAM, `/health` OK, `/v1/models` reports
  `qwen3.5-9b` (8.95 B parameters); a chat request returned `OK`.
- Real-data Base pilot (`math-informal-real.json`, 6 steps / 20k tokens):
  MATH-500 **9/20**, AIME 2024 **0/10**, all 30 runs valid.
- Two-phase formal smoke (`math-batch-5090.json`, no `--release-model`):
  4/4 collected, 4/4 valid 0/1 (solutions still `sorry`), server stayed up.
- Full precheck (`--workers 8`): **493/499 OK, 6 failed**; miniF2F
  **488/488**; ProofNet 5/11 files / **66 theorems**. The six excluded files
  are pre-v4.33 Mathlib API.
- Frozen Putnam subset (`freeze_math_protocol.py --check-putnam`,
  100 tasks): **100/100 rc=0** with the original `sorry`.
- Lean compile of `src/putnam_1962_a1.lean` via the wrapper: rc 0 with the
  expected `sorry` warning; miniF2F/ProofNet integration test 7.5 s.
- Harness v2 smoke (4 tasks): the v2b 512-token run truncated the fenced
  Lean write before its closing fence; the v2c 4096-token run logged `write`
  actions on Putnam a2 and ProofNet. All four graded valid 0/1 because the
  proof content was still wrong; the frozen formal protocols use 4096 and
  30k/100k E.


