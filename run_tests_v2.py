#!/usr/bin/env python3
"""Run the test suite using subprocess."""
import subprocess
import sys
import os

os.chdir('/Users/ankit/Desktop/Systematic Literature Review/FL_SLR_Automation')
sys.path.insert(0, '/Users/ankit/Desktop/Systematic Literature Review/FL_SLR_Automation')

os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
os.environ.setdefault('APP_ENV', 'testing')

# First ensure venv exists and has dependencies
venv_python = '/Users/ankit/Desktop/Systematic Literature Review/FL_SLR_Automation/.venv/bin/python3'

if not os.path.exists(venv_python):
    print("Virtual environment not found. Creating...")
    result = subprocess.run([sys.executable, '-m', 'venv', '.venv'], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Failed to create venv: {result.stderr}")
        sys.exit(1)
    print("Installing dependencies...")
    pip_result = subprocess.run(
        [venv_python, '-m', 'pip', 'install', '-r', 'requirements.txt'],
        capture_output=True, text=True
    )
    if pip_result.returncode != 0:
        print(f"pip install failed: {pip_result.stderr}")
        sys.exit(1)

# Run tests
result = subprocess.run(
    [venv_python, '-m', 'pytest', 'tests/', '-v', '--tb=short', '-x'],
    capture_output=False,
    text=True
)
sys.exit(result.returncode)
