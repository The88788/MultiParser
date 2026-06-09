@echo off
echo Copying logs from 88788 MultiParser...
robocopy C:\MultiParser\logs \\tsclient\R\ /MIR /NP

echo.
echo Copying output Excel from 88788 MultiParser...
robocopy C:\MultiParser\output \\tsclient\R\ /MIR /NP /XO

if %errorlevel% leq 1 (
    echo.
    echo [OK] Done
) else (
    echo.
    echo [ERROR] Check that R: drive is connected in RDP settings
)
pause
