@echo off
echo ================================================================
echo  TPM SYSTEM - DEVELOPMENT SETUP
echo ================================================================
echo.

echo Checking Python installation...
python --version
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python 3.8+ from https://python.org
    pause
    exit /b 1
)

echo.
echo Installing Python dependencies...
pip install -r requirements.txt

if %ERRORLEVEL% neq 0 (
    echo ERROR: Failed to install dependencies
    echo Please check your internet connection and try again
    pause
    exit /b 1
)

echo.
echo ================================================================
echo  SETUP COMPLETED SUCCESSFULLY!
echo ================================================================
echo.
echo To run the application:
echo   python src/app.py
echo.
echo To build executable:
echo   build_executable.bat
echo.
echo Default login: admin / admin123
echo Web interface: http://localhost:8080
echo.
pause