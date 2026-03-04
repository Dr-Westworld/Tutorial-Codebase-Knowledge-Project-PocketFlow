#!/usr/bin/env python
"""
Virtual Environment Flask App Runner
This script activates the virtual environment and runs the Flask app
"""

import os
import sys
import subprocess
import venv
from pathlib import Path

def get_venv_path():
    """Get or create virtual environment path"""
    project_root = Path(__file__).parent
    venv_path = project_root / ".venv"
    # print(venv_path)
    return venv_path

def create_venv_if_needed():
    """Create virtual environment if it doesn't exist"""
    venv_path = get_venv_path()

    if not venv_path.exists():
        print(f"Creating virtual environment at {venv_path}...")
        venv.create(venv_path, with_pip=True)
        print("Virtual environment created successfully!")
    else:
        print(f"Virtual environment already exists at {venv_path}")
 
def get_python_executable():
    """Get the Python executable path for the virtual environment"""
    venv_path = get_venv_path()

    if sys.platform == 'win32':
        python_exe = venv_path / "Scripts" / "python.exe"
    else:
        python_exe = venv_path / "bin" / "python"

    return python_exe

def get_pip_executable():
    """Get the pip executable path for the virtual environment"""
    venv_path = get_venv_path()

    if sys.platform == 'win32':
        pip_exe = venv_path / "Scripts" / "pip.exe"
    else:
        pip_exe = venv_path / "bin" / "pip"

    return pip_exe

# def install_requirements():
#     """Install requirements in virtual environment"""
#     pip_exe = get_pip_executable()
#     project_root = Path(__file__).parent

#     # Install main requirements
#     main_req = project_root / "requirements.txt"
#     if main_req.exists():
#         print(f"\nInstalling main requirements from {main_req}...")
#         subprocess.run([str(pip_exe), "install", "-r", str(main_req)], check=True)
#     else:
#         print(f"Warning: {main_req} not found")

#     # Install app requirements
#     app_req = project_root / "requirements-app.txt"
#     if app_req.exists():
#         print(f"\nInstalling app requirements from {app_req}...")
#         subprocess.run([str(pip_exe), "install", "-r", str(app_req)], check=True)
#     else:
#         print(f"Warning: {app_req} not found")

def run_app(debug=True, host='localhost', port=5000):
    """Run the Flask app using the virtual environment Python"""
    python_exe = get_python_executable()
    project_root = Path(__file__).parent
    app_file = project_root / "app.py"

    if not app_file.exists():
        print(f"Error: {app_file} not found!")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"Starting Flask App")
    print(f"{'='*60}")
    print(f"Python: {python_exe}")
    print(f"Host: {host}")
    print(f"Port: {port}")
    print(f"Debug: {debug}")
    print(f"{'='*60}\n")

    # Build environment variables
    env = os.environ.copy()
    env['PYTHONUNBUFFERED'] = '1'
    env['FLASK_APP'] = str(app_file)
    env['FLASK_DEBUG'] = '1' if debug else '0'

    # Run the app
    cmd = [str(python_exe), str(app_file)]

    try:
        subprocess.run(cmd, env=env, check=True)
    except KeyboardInterrupt:
        print("\n\nApp stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"Error running app: {e}")
        sys.exit(1)

def main():
    """Main entry point"""
    try:
        # Step 1: Create venv if needed
        create_venv_if_needed()

        # # Step 2: Install requirements
        # print("\nInstalling requirements...")
        # install_requirements()

        # Step 3: Run the app
        run_app(debug=True, host='localhost', port=5000)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
