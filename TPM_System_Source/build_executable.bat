@echo off
echo ================================================================
echo  BUILDING TPM SYSTEM EXECUTABLE
echo ================================================================
echo.

REM Clean previous builds
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo Building executable with PyInstaller...
pyinstaller build/app.spec

if %ERRORLEVEL% neq 0 (
    echo.
    echo ================================================================
    echo  BUILD FAILED!
    echo ================================================================
    echo Please check that PyInstaller is installed: pip install pyinstaller
    pause
    exit /b 1
)

echo.
echo Copying additional files to distribution...
copy src\OperationalExcellence.ico dist\TPM_System\
copy templates\*.html dist\TPM_System\_internal\templates\

echo.
echo Creating user-friendly launcher...
echo @echo off > dist\TPM_System\start_tpm_system.bat
echo echo Starting TPM System... >> dist\TPM_System\start_tpm_system.bat
echo TPM_System.exe >> dist\TPM_System\start_tpm_system.bat

echo.
echo ================================================================
echo  BUILD COMPLETED SUCCESSFULLY!
echo ================================================================
echo.
echo Executable location: dist\TPM_System\TPM_System.exe
echo Launcher script: dist\TPM_System\start_tpm_system.bat
echo.
echo The GUI version runs in the background with system tray integration.
echo No console window will be visible during operation.
echo.
pause