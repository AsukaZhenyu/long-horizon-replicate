# Start the local Qwen3.5-9B VLM (text + image) with the matching mmproj.
# Usage: powershell -ExecutionPolicy Bypass -File .\start_llama_vlm.ps1 -Ngl 22
# 22 layers: vision works, text decode ~7.6 t/s, VRAM ~5.76/6.14 GB.
# 20 layers: more headroom, text decode ~6.5 t/s.
param([int]$Ngl = 22)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$exe = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\llama.exe"
$model = Join-Path $root ".cache\models\qwen3.5-9b-q4_k_m.gguf"
$mmproj = Join-Path $root ".cache\models\mmproj-F16.gguf"
$out = Join-Path $root ".cache\server\vlm-stdout.log"
$err = Join-Path $root ".cache\server\vlm-stderr.log"

Get-Process llama -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3

$args = @(
  "serve",
  "-m", "$model",
  "--mmproj", "$mmproj",
  "-c", "16384",
  "--parallel", "1",
  "-ngl", "$Ngl",
  "--cache-type-k", "bf16",
  "--cache-type-v", "bf16",
  "--mmproj-offload",
  "--image-min-tokens", "1024",
  "--image-max-tokens", "1024",
  "--reasoning", "off",
  "--threads", "4",
  "--threads-http", "2",
  "--host", "127.0.0.1",
  "--port", "8080",
  "--alias", "qwen3.5-9b",
  "--cache-ram", "256"
)
Write-Output "starting VLM ngl=$Ngl"
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
