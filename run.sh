#!/bin/bash
set -e
clear

# Path to Python 3.13
PYTHON_PATH="/usr/bin/python3.13"

echo "[1/7] Checking virtual environment..."
if [ ! -d ".venv" ]; then
    echo "[1/7] Creating virtual environment with Python 3.13..."
    "$PYTHON_PATH" -m venv .venv
fi

echo "[2/7] Activating environment..."
source .venv/bin/activate

echo "[3/7] Upgrading pip and setuptools..."
python -m pip install --upgrade pip setuptools wheel

echo "[4/7] Installing dependencies from requirements2.txt..."
pip install -r requirements2.txt

echo "[5/7] Removing incompatible aiodns (if present)..."
pip uninstall -y aiodns || true

echo "[6/7] Installing pandas_ta..."
pip install pandas-ta==0.4.71b0

echo "[7/7] Running main.py..."
python main.py

echo
echo "✅ All done."
