@echo off
setlocal EnableExtensions
chcp 65001 >nul

rem ------------------------------------------------------------------
rem  Long-horizon coverage runner
rem
rem  Double-click this file.  It runs in its own console, so Claude
rem  Code's low-memory background reaper cannot stop it.
rem
rem  Closing this window stops the batch.  Rerun the same option to
rem  resume: finished runs are skipped via the append-only ledger.
rem ------------------------------------------------------------------

cd /d "%~dp0"

set "PY=%~dp0.cache\venv\Scripts\python.exe"
set "RUNNER=%~dp0experiments\adapters\repro_matrix.py"
set "PROTO1M=%~dp0experiments\adapters\protocols\coverage-1m.json"
set "PROTOCOW=%~dp0experiments\adapters\protocols\coverage-cowthello-10h.json"
set "PROTOCOWALL=%~dp0experiments\adapters\protocols\coverage-cowthello-10h-all.json"
set "OUTDIR1M=%~dp0experiments\adapters\results\coverage-1m"
set "OUTDIRCOW=%~dp0experiments\adapters\results\cowthello-10h"
set "OUTDIRCOWALL=%~dp0experiments\adapters\results\cowthello-10h-all"
set "WORKERS=1"
set "PYTHONUNBUFFERED=1"

if not exist "%PY%"       goto missing
if not exist "%RUNNER%"   goto missing
if not exist "%PROTO1M%"    goto missing
if not exist "%PROTOCOW%"   goto missing
if not exist "%PROTOCOWALL%" goto missing
if not exist "%OUTDIR1M%"      mkdir "%OUTDIR1M%"
if not exist "%OUTDIRCOW%"     mkdir "%OUTDIRCOW%"
if not exist "%OUTDIRCOWALL%"  mkdir "%OUTDIRCOWALL%"

docker info >nul 2>&1
if errorlevel 1 (
  echo.
  echo Docker is not running. Start Docker Desktop, wait until it is ready,
  echo then run this script again.
  echo.
  pause
  exit /b 1
)
for /f %%c in ('docker ps -q --filter "name=adapter-"') do set "STALE=1"

for /f %%i in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmmss"') do set "STAMP=%%i"

:menu
set "PROTO=%PROTO1M%"
set "OUTDIR=%OUTDIR1M%"
cls
echo ============================================================
echo  Long-horizon coverage matrix
echo  model: qwen3.5-9b
echo ============================================================
echo   1. Resume full 1M 4x4 batch (16 runs, 1 worker)
echo   2. 1M fast set: LHTB + CORE + MLE  (skip TB)
echo   3. 1M TB only  (the long pole)
echo   4. Show status  (no run)
echo   5. Exit
echo   6. Remove leftover adapter-* containers
echo   7. Rerun ALL 16 at 1M from scratch (fixed context policy)
echo   8. Rerun only tb21/rrsi at 1M (fixed context policy)
echo   9. cowthello pilot: Base  (E=600k, ~10-17h)
echo  10. cowthello: all 4 methods (multi-day)
echo.
echo  Closing this window stops the batch.
echo  Rerun the same option to resume; finished runs are skipped.
if defined STALE echo  WARNING: leftover adapter-* containers found; press 6 to remove.
echo.
choice /c 1234567890 /n /t 15 /d 1 /m "Select [1-10] (default 1 in 15s): "
if errorlevel 10 goto run_cow_all
if errorlevel 9 goto run_cow_pilot
if errorlevel 8 goto run_fresh_rrsi
if errorlevel 7 goto run_fresh_all
if errorlevel 6 goto cleanup
if errorlevel 5 goto end
if errorlevel 4 goto run_status
if errorlevel 3 goto run_tb
if errorlevel 2 goto run_fast
if errorlevel 1 goto run_all
goto menu

:run_all
set "OUTDIR=%OUTDIR1M%"
set "PROTO=%PROTO1M%"
set "FRESH="
set "ARGS="
goto launch

:run_fast
set "OUTDIR=%OUTDIR1M%"
set "PROTO=%PROTO1M%"
set "FRESH="
set "ARGS=--only lhtb2,core,mle"
goto launch

:run_tb
set "OUTDIR=%OUTDIR1M%"
set "PROTO=%PROTO1M%"
set "FRESH="
set "ARGS=--only tb21"
goto launch

:run_fresh_all
set "OUTDIR=%OUTDIR1M%"
set "PROTO=%PROTO1M%"
set "FRESH=--fresh"
set "ARGS="
goto launch

:run_fresh_rrsi
set "OUTDIR=%OUTDIR1M%"
set "PROTO=%PROTO1M%"
set "FRESH=--fresh"
set "ARGS=--only tb21/rrsi"
goto launch

:run_cow_pilot
set "OUTDIR=%OUTDIRCOW%"
set "PROTO=%PROTOCOW%"
set "FRESH="
set "ARGS="
goto launch

:run_cow_all
set "OUTDIR=%OUTDIRCOWALL%"
set "PROTO=%PROTOCOWALL%"
set "FRESH="
set "ARGS="
goto launch

:run_status
"%PY%" "%RUNNER%" "%PROTO%" --status
echo.
echo  cowthello pilot status:
echo  "%PY%" "%RUNNER%" "%PROTOCOW%" --status
echo  cowthello all-methods status:
echo  "%PY%" "%RUNNER%" "%PROTOCOWALL%" --status
echo.
pause
goto menu

:cleanup
echo.
echo Removing all containers named adapter-* ...
for /f "tokens=*" %%c in ('docker ps -aq --filter "name=adapter-"') do (
  echo   removing %%c
  docker rm -f %%c >nul 2>&1
)
echo Done.
echo.
pause
goto menu

:launch
set "LOG=%OUTDIR%\run-%STAMP%.log"
echo.
echo Log: %LOG%
echo Starting... (this can take hours; progress is shown below)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -Command "& '%PY%' '%RUNNER%' '%PROTO%' --workers %WORKERS% %FRESH% %ARGS% 2>&1 | Tee-Object -FilePath '%LOG%'; exit $LASTEXITCODE"
set "RC=%ERRORLEVEL%"
echo.
echo ============================================================
if "%RC%"=="0" (
  echo Finished. Exit code 0.
) else (
  echo Finished with exit code %RC%. Check the log and matrix.
)
echo.
echo Log:    %LOG%
echo Matrix: %OUTDIR%\matrix.json
echo Status: "%PY%" "%RUNNER%" "%PROTO%" --status
echo ============================================================
echo.
pause
goto end

:missing
echo.
echo Required path not found:
echo   venv python: %PY%
echo   runner:      %RUNNER%
echo   protocols:   %PROTO1M%
echo                %PROTOCOW%
echo                %PROTOCOWALL%
echo.
pause
exit /b 1

:end
endlocal
