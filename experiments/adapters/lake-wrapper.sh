#!/usr/bin/env bash
# Bypass Lake's package/git checks on the 5090 host.
#
# `lake env lean X` runs the pinned Linux Lean with LEAN_PATH pointing at the
# transferred Mathlib builds.  Without this, Lake can decide that the Mathlib
# package URL changed (because .git was not transferred) and delete/re-clone it.
#
# Install:
#   mkdir -p .cache/tools/lean-wrapper/bin
#   cp experiments/adapters/lake-wrapper.sh .cache/tools/lean-wrapper/bin/lake
#   chmod +x .cache/tools/lean-wrapper/bin/lake
#   export PUTNAM_LEAN_BIN=$PWD/.cache/tools/lean-wrapper/bin/lake
set -euo pipefail

ROOT="${LH_REPO:-/home/lzy/long-horizon-replicate}"
TC="$ROOT/.cache/tools/lean4-4.33.1/lean-4.33.1-linux"
P="$ROOT/.cache/upstream/putnambench/lean4"

if [ "${1:-}" = "env" ] && [ "${2:-}" = "lean" ]; then
  shift 2
  export LEAN_PATH="$P/.lake/packages/Cli/.lake/build/lib/lean:$P/.lake/packages/batteries/.lake/build/lib/lean:$P/.lake/packages/Qq/.lake/build/lib/lean:$P/.lake/packages/aesop/.lake/build/lib/lean:$P/.lake/packages/proofwidgets/.lake/build/lib/lean:$P/.lake/packages/importGraph/.lake/build/lib/lean:$P/.lake/packages/LeanSearchClient/.lake/build/lib/lean:$P/.lake/packages/plausible/.lake/build/lib/lean:$P/.lake/packages/mathlib/.lake/build/lib/lean:$P/.lake/build/lib/lean:$TC/lib/lean"
  exec "$TC/bin/lean" "$@"
fi
exec "$TC/bin/lake" "$@"
