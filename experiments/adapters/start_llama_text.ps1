# Start the local Qwen3.5-9B in fast text-only mode (no mmproj).
# Usage: powershell -ExecutionPolicy Bypass -File .\start_llama_text.ps1 -Ngl 26
# 26 layers: text decode ~10.8 t/s, prefill ~694 t/s, no vision.
param([int]$Ngl = 26)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$exe = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\llama.exe"
$model = Join-Path $root ".cache\models\qwen3.5-9b-q4_k_m.gguf"
$out = Join-Path $root ".cache\server\text-stdout.log"
$err = Join-Path $root ".cache\server\text-stderr.log"

Get-Process llama -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3

$args = @(
  "serve",
  "-m", "$model",
  "-c", "16384",
  "--parallel", "1",
  "-ngl", "$Ngl",
  "--cache-type-k", "bf16",
  "--cache-type-v", "bf16",
  "--reasoning", "off",
  "--threads", "4",
  "--threads-http", "2",
  "--host", "127.0.0.1",
  "--port", "8080",
  "--alias", "qwen3.5-9b",
  "--cache-ram", "256"
)
Write-Output "starting text-only ngl=$Ngl"
$p = Start-Process -FilePath $exe -ArgumentList $args -WorkingDirectory $root `
  -RedirectStandardOutput $out -RedirectStandardError $err `
  -WindowStyle Hidden -PassThru
Write-Output "PID=$($p.Id)"

for ($i = 0; $i -lt 90; $i++) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:8080/health" -TimeoutSec 2
    if ($r.StatusCode -eq 200) { Write-Output "READY"; break }
  } catch {}
  Start-Sleep -Seconds 2
}
