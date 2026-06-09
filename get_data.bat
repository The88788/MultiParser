@echo off
echo What to copy?
echo   1 - logs
echo   2 - output
echo.
choice /C 12 /N /M "Press 1 or 2: "
set CHOICE=%errorlevel%

if %CHOICE%==1 (
    echo Copying logs from 88788 MultiParser...
    robocopy C:\MultiParser\logs \\tsclient\R\ /MIR /NP
)
if %CHOICE%==2 (
    echo Copying output Excel from 88788 MultiParser...
    robocopy C:\MultiParser\output \\tsclient\R\ /MIR /NP /XO
)

if %errorlevel% leq 1 (
    echo.
    echo [OK] Done
) else (
    echo.
    echo [ERROR] Check that R: drive is connected in RDP settings
)
pause
