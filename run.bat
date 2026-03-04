@echo off
REM Color codes for Windows
setlocal enabledelayedexpansion

REM Get the directory where this script is located
set PROJECT_ROOT=%~dp0
set VENV_PATH=%PROJECT_ROOT%venv

echo.
echo ========================================
echo Code Tutorial Generator - Web App
echo ========================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python is not installed or not in PATH
    exit /b 1
)

REM Step 1: Create virtual environment if it doesn't exist
if not exist "%VENV_PATH%" (
    echo Creating virtual environment...
    python -m venv "%VENV_PATH%"
    if errorlevel 1 (
        echo Error: Failed to create virtual environment
        exit /b 1
    )
    echo Virtual environment created successfully!
) else (
    echo Virtual environment already exists
)

REM Step 2: Activate virtual environment
echo Activating virtual environment...
call "%VENV_PATH%\Scripts\activate.bat"

REM Step 3: Upgrade pip
echo Upgrading pip...
python -m pip install --upgrade pip

REM Step 4: Install requirements
if exist "%PROJECT_ROOT%requirements.txt" (
    echo Installing main requirements...
    pip install -r "%PROJECT_ROOT%requirements.txt"
)

if exist "%PROJECT_ROOT%requirements-app.txt" (
    echo Installing app requirements...
    pip install -r "%PROJECT_ROOT%requirements-app.txt"
)

REM Step 5: Run the Flask app
echo.
echo ========================================
echo Starting Flask Application
echo ========================================
echo URL: http://localhost:5000
echo Press Ctrl+C to stop the server
echo ========================================
echo.

cd /d "%PROJECT_ROOT%"
python app.py

pause
