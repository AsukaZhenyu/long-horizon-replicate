#!/usr/bin/env bash
# Start the local Qwen3.5-9B in text-only mode on the Linux/5090 host.
# Usage: bash experiments/adapters/start_llama_text.sh
# Override LLAMA_DIR / LLAMA_BIN / MODEL if the paths differ.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LLAMA_DIR="${LLAMA_DIR:-$HOME/work/llama.cpp-b8705}"
BIN="${LLAMA_BIN:-$LLAMA_DIR/build/bin/llama-server}"
MODEL="${MODEL:-$ROOT/.cache/models/qwen3.5-9b-q4_k_m.gguf}"
SERVER_DIR="$ROOT/.cache/server"
mkdir -p "$SERVER_DIR"

pkill -f "llama-server.*$(basename "$MODEL")" 2>/dev/null || true
sleep 2

export LD_LIBRARY_PATH="/usr/local/cuda-12.9/lib64:$LLAMA_DIR/build/bin:${LD_LIBRARY_PATH:-}"
nohup "$BIN" \
  -m "$MODEL" \
  -c 16384 --parallel 1 -ngl 99 \
  --cache-type-k bf16 --cache-type-v bf16 \
  --reasoning off --threads 16 --threads-http 4 \
  --host 127.0.0.1 --port 8080 --alias qwen3.5-9b --cache-ram 256 \
  > "$SERVER_DIR/text-stdout.log" 2> "$SERVER_DIR/text-stderr.log" &
echo "PID=$!"

for _ in $(seq 1 120); do
  if python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=2)" 2>/dev/null; then
    echo READY
    exit 0
  fi
  sleep 2
done
echo "not ready; see $SERVER_DIR/text-stderr.log"
exit 1
