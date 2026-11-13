# Copy the TB8 domain adapter into the local RRSI checkout.
#   powershell -NoProfile -ExecutionPolicy Bypass -File ...\install.ps1
$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..\..')).Path
$dest = Join-Path $repo '.cache\upstream\rrsi\domains\tb8'
if (-not (Test-Path (Join-Path $repo '.cache\upstream\rrsi\domains'))) {
    throw "RRSI checkout not found under $repo\.cache\upstream\rrsi; run setup first"
}
New-Item -ItemType Directory -Force $dest | Out-Null
Copy-Item -Force (Join-Path $PSScriptRoot '*') $dest -Recurse
Write-Host "installed TB8 domain -> $dest"
