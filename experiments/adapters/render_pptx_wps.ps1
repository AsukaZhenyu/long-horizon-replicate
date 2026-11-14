# Render a .pptx to PNG slides via WPS Presentation COM.
# No LibreOffice/PowerPoint required; WPS Office must be installed.
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\render_pptx_wps.ps1 `
#     -Pptx .cache\ppt-smoke\smoke.pptx -OutDir .cache\ppt-smoke\render
# Output files are named 幻灯片1.PNG, 幻灯片2.PNG, ... (WPS locale).
param(
  [string]$Pptx = ".cache/ppt-smoke/smoke.pptx",
  [string]$OutDir = ".cache/ppt-smoke/render",
  [int]$Width = 1600,
  [int]$Height = 900
)
$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
if (-not [System.IO.Path]::IsPathRooted($Pptx)) { $Pptx = Join-Path $root $Pptx }
if (-not [System.IO.Path]::IsPathRooted($OutDir)) { $OutDir = Join-Path $root $OutDir }
$pptx = (Resolve-Path $Pptx).Path
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$app = New-Object -ComObject KWPP.Application
Start-Sleep -Seconds 2
try {
  $pres = $app.Presentations.Open("$pptx", $true, $false, $false)
  $pres.Export("$OutDir", "PNG", $Width, $Height)
  $pres.Close()
  Write-Output "rendered $($pres.Slides.Count) slides to $OutDir"
} finally {
  try { $app.Quit() } catch {}
}
