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
- `prepare_formal_math.py --precheck --only minif2f --workers 8 --no-copy`
  runs the full compatibility check on this host.

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
